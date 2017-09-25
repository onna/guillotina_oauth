# -*- coding: utf-8 -*-
from setuptools import find_packages
from setuptools import setup

setup(
    name='guillotina_oauth',
    description='guillotina oauth support',
    version=open('VERSION').read().strip(),
    long_description=(open('README.rst').read() + '\n' +
                      open('CHANGELOG.rst').read()),
    classifiers=[
        'Programming Language :: Python :: 3.6',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
    keywords='guillotina oauth',
    author='Ramon Navarro Bosch',
    author_email='ramon@plone.org',
    url='https://pypi.python.org/pypi/guillotina_oauth',
    license='GPL version 3',
    setup_requires=[
        'pytest-runner',
    ],
    zip_safe=True,
    include_package_data=True,
    packages=find_packages(exclude=['ez_setup']),
    install_requires=[
        'setuptools',
        'guillotina',
        'ujson',
        'pyjwt',
        'lru-dict'
    ],
    tests_require=[
        'pytest',
    ],
    entry_points={
        'guillotina': [
            'include = guillotina_oauth',
        ]
    }
)
