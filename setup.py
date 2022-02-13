from setuptools import setup, find_packages


with open('README.md', 'r') as f:
    long_description = f.read()


with open('requirements.txt', 'r') as f:
    dependencies = f.read().splitlines()


setup(
    name='qbt_migrate',
    version='2.1.2',
    packages=find_packages(),
    install_requires=dependencies,
    description='Migrate qBittorrent FastResume files.',
    long_description=long_description,
    long_description_content_type='text/markdown',
    author='jslay88',
    url='https://github.com/jslay88/qbt_migrate',
    entry_points={
        'console_scripts': [
            'qbt_migrate = qbt_migrate.cli:main'
        ]
    },
    python_requires='>=3.6.4'
)
