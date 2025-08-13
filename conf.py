import os
import sys
sys.path.insert(0, os.path.abspath('..'))

project = 'LogWatcher'
copyright = '2025, Anil Prajapati'
author = 'Anil Prajapati'
release = '1.0'

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.viewcode',
]

templates_path = ['_templates']
exclude_patterns = []

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']
