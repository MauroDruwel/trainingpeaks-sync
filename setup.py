import os
import re
from pathlib import Path
from setuptools import setup, find_packages


def read(file_name):
    with open(
        os.path.join(
            Path(os.path.dirname(__file__)),
            file_name
        ),
        encoding='utf-8'
    ) as _file:
        return _file.read()


setup(
    name="trainingpeaks-sync",
    version=re.findall(
        re.compile(r'[0-9]+\.[0-9]+\.[0-9]+'),
        read('__version__.py')
    )[0],
    author="Mauro Druwel",
    description="Multi-source workout aggregator & sync engine for TrainingPeaks (Strava, LAGO & StudentApp)",
    packages=find_packages(),
    install_requires=[
        "defusedxml>=0.7.1",
        "numpy>=1.26.0",
        "openai>=1.0.0",
        "pandas>=2.0.0",
        "python-dotenv>=1.0.0",
        "questionary>=2.0.0",
        "requests>=2.28.0",
        "scipy>=1.11.0",
        "tcxreader>=0.4.11",
        "tqdm>=4.66.0"
    ],
    extras_require={
        "dev": [
            "pytest>=8.0.0",
            "pytest-cov>=5.0.0"
        ]
    },
    entry_points={
        "console_scripts": [
            "trainingpeaks-sync=src.cli:main",
            "tp-sync=src.cli:main",
            "strava-to-trainingpeaks=src.cli:main",
            "strava-sync=src.cli:main",
            "strava-coach-mode=src.coach_sync:coach_mode_main",
        ],
    },
)
