"""PyInstaller hook: echopype ships YAML/XML resources it loads at runtime."""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files("echopype", includes=["**/*.yaml", "**/*.yml", "**/*.json", "**/*.xml"])
datas += collect_data_files("echopype")
hiddenimports = collect_submodules("echopype")
