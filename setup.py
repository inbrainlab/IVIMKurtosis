from setuptools import setup, find_packages

setup(
    name='IVIM Kurtosis Implementation',
    version='1.0',
    packages=["kurtosis"],
    package_dir={
        "": ".",
        "kurtosis": "./",

    },
)
