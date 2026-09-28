import aifw


def test_version_is_string():
    assert hasattr(aifw, "__version__")
    assert isinstance(aifw.__version__, str)


def test_name_is_string():
    assert hasattr(aifw, "__name__")
    assert isinstance(aifw.__name__, str)
