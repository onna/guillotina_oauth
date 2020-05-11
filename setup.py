# -*- coding: utf-8 -*-
from setuptools import find_packages
from setuptools import setup


setup(
    name="guillotina_oauth",
    description="guillotina oauth support",
    version=open("VERSION").read().strip(),
    long_description=(open("README.rst").read() + "\n" + open("CHANGELOG.rst").read()),
    classifiers=[
        "Programming Language :: Python :: 3.6",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    keywords="guillotina oauth",
    author="Ramon Navarro Bosch",
    author_email="ramon@plone.org",
    url="https://pypi.python.org/pypi/guillotina_oauth",
    license="GPL version 3",
    setup_requires=["pytest-runner"],
    zip_safe=True,
    include_package_data=True,
    packages=find_packages(exclude=["ez_setup"]),
    package_data={"": ["*.txt", "*.rst"], "guillotina_oauth": ["py.typed"]},
    install_requires=[
        "setuptools",
        "guillotina>=4.0.0",
        "ujson",
        "pyjwt",
        "lru-dict",
        "aiohttp-client-manager",
    ],
    extras_require={
        "test": ["pytest", "pre-commit==1.18.2", "black==19.10b0", "isort==4.3.21", "pytest-docker-fixtures==1.3.7"],
    },
    entry_points={"guillotina": ["include = guillotina_oauth"]},
)
