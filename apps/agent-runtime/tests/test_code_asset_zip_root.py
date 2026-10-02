from engine.tools.code_asset import single_root_prefix


def test_one_folder_is_stripped():
    assert single_root_prefix(["proj/", "proj/main.py", "proj/README.md"]) == "proj/"


def test_flat_zip_is_left_alone():
    assert single_root_prefix(["main.py", "README.md"]) == ""


def test_two_top_level_folders_are_left_alone():
    assert single_root_prefix(["a/main.py", "b/util.py"]) == ""


def test_macos_metadata_does_not_count():
    assert single_root_prefix(["proj/main.py", "__MACOSX/proj/._main.py"]) == "proj/"


def test_a_lone_file_named_like_a_folder_is_not_a_root():
    assert single_root_prefix(["proj"]) == ""
