"""
Trackpoint processor for cleaning and reducing TCX data before analysis.
"""
import logging
from typing import Optional

import numpy as np
import pandas as pd
from scipy.spatial.distance import pdist, squareform
from tcxreader.tcxreader import TCXReader
from tqdm import tqdm

from ..models import ProcessingConfig


logger = logging.getLogger(__name__)


class TrackpointProcessor:
    """Processor for trackpoint data preprocessing."""

    def __init__(self, config: Optional[ProcessingConfig] = None):
        self.config = config or ProcessingConfig()
        self.logger = logging.getLogger(__name__)

    def process(self, tcx_data: TCXReader) -> pd.DataFrame:
        """Process trackpoints data."""
        df = self._create_dataframe(tcx_data)
        df = self._clean_and_transform(df)
        df = self._reduce_data_size(df)
        df = self._format_time_column(df)
        return df

    def _create_dataframe(self, tcx_data: TCXReader) -> pd.DataFrame:
        """Create initial dataframe from TCX data."""
        df = pd.DataFrame(tcx_data.trackpoints_to_dict())

        column_mapping = {
            "distance": "Distance_Km",
            "time": "Time",
            "Speed": "Speed_Kmh"
        }
        df.rename(columns=column_mapping, inplace=True)
        return df

    def _clean_and_transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Clean and transform the dataframe."""
        df["Time"] = df["Time"].apply(lambda x: x.value / 10**9)
        df["Distance_Km"] = round(df["Distance_Km"] / 1000, 2)
        df["Speed_Kmh"] = df["Speed_Kmh"] * 3.6
        df["Pace"] = round(
            df["Speed_Kmh"].apply(lambda x: 60 / x if x > 0 else 0),
            2
        )

        df = self._remove_sparse_columns(df)
        df = df.drop_duplicates().reset_index(drop=True)
        df = df.dropna(subset=["Speed_Kmh", "Pace", "Distance_Km"])
        return df

    def _remove_sparse_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Remove columns with too many null values."""
        columns_to_check = ["cadence", "hr_value", "latitude", "longitude"]
        threshold = len(df) / 2

        for column in columns_to_check:
            if column in df.columns and df[column].isnull().sum() >= threshold:
                if column in ["latitude", "longitude"]:
                    df.drop(
                        columns=["latitude", "longitude"],
                        inplace=True,
                        errors='ignore'
                    )
                df.drop(columns=[column], inplace=True, errors='ignore')

        return df

    def _reduce_data_size(self, df: pd.DataFrame) -> pd.DataFrame:
        """Reduce data size using euclidean distance filtering."""
        row_count = len(df)

        if row_count > self.config.large_dataset_threshold:
            threshold = self.config.euclidean_threshold_large
        elif row_count > self.config.medium_dataset_threshold:
            threshold = self.config.euclidean_threshold_medium
        else:
            threshold = self.config.euclidean_threshold_small

        return self._apply_euclidean_filtering(df, threshold)

    def _apply_euclidean_filtering(self, df: pd.DataFrame, percentage: float) -> pd.DataFrame:
        """Apply euclidean distance filtering to reduce similar points."""
        if len(df) < 50:
            return df

        numeric_df = df.select_dtypes(include=[np.number])
        if numeric_df.empty:
            return df

        try:
            distances = pdist(numeric_df, metric='euclidean')
            distance_matrix = squareform(distances)
            np.fill_diagonal(distance_matrix, np.inf)

            rows_to_remove = int(percentage * len(df))
            indices_to_drop = set()

            with tqdm(total=rows_to_remove, desc="Filtering similar points") as pbar:
                for _ in range(rows_to_remove):
                    if len(indices_to_drop) >= len(df) - 10:
                        break

                    min_idx = np.argmin(distance_matrix)
                    row, col = np.unravel_index(min_idx, distance_matrix.shape)

                    if row not in indices_to_drop and col not in indices_to_drop:
                        indices_to_drop.add(row)
                        distance_matrix[row, :] = np.inf
                        distance_matrix[:, row] = np.inf
                        pbar.update(1)

            df = df.drop(index=list(indices_to_drop)).reset_index(drop=True)

        except Exception as err:
            self.logger.warning(
                "Failed to apply euclidean filtering: %s",
                str(err)
            )

        return df

    def _format_time_column(self, df: pd.DataFrame) -> pd.DataFrame:
        """Format time column to HH:MM:SS."""
        df["Time"] = pd.to_datetime(
            df["Time"],
            unit='s'
        ).dt.strftime('%H:%M:%S')
        return df
