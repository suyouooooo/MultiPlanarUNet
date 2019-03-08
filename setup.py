from setuptools import setup, find_packages

from MultiPlanarUNet import __version__

with open('README.md') as readme_file:
    readme = readme_file.read()

with open('HISTORY.rst') as history_file:
    history = history_file.read().replace('.. :changelog:', '')

with open("requirements.txt") as req_file:
    requirements = list(filter(None, req_file.read().split("\n")))

setup(
    name='MultiPlanarUNet',
    version=__version__,
    description='Multi-Planar UNet for autonomous segmentation of 3D medical images',
    long_description=readme + "\n\n" + history,
    author='Mathias Perslev',
    author_email='map@di.ku.dk',
    url='https://github.com/perslev/MultiPlanarUNet',
    license="LICENSE.txt",
    packages=find_packages(),
    package_dir={'MultiPlanarUNet':
                 'MultiPlanarUNet'},
    include_package_data=True,
    entry_points={
       'console_scripts': [
           'mp=MultiPlanarUNet.bin.mp:entry_func',
       ],
    },
    install_requires=requirements,
    classifiers=['Development Status :: 3 - Alpha',
                 'Environment :: Console',
                 'Operating System :: POSIX',
                 'Programming Language :: Python :: 3',
                 'Programming Language :: Python :: 3.5',
                 'Programming Language :: Python :: 3.6',
                 'Programming Language :: Python :: 3.7'
                 'License :: OSI Approved :: MIT License']
)
