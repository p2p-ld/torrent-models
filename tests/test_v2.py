import pytest

from torrent_models.v2 import FileTree

# add test cases of paired flattened and unflattened file trees here:

FILE_TREES = (
    {
        b"directory": {
            b"file1.exe": {b"": {b"length": 1, b"pieces root": b"sup"}},
            b"subdir": {b"file2.exe": {b"": {b"length": 2, b"pieces root": b"sup"}}},
        },
        b"file3.exe": {b"": {b"length": 3, b"pieces root": b"sup"}},
    },
)

FLAT_FILE_TREES = (
    {
        b"directory/file1.exe": {b"length": 1, b"pieces root": b"sup"},
        b"directory/subdir/file2.exe": {b"length": 2, b"pieces root": b"sup"},
        b"file3.exe": {b"length": 3, b"pieces root": b"sup"},
    },
)


@pytest.mark.parametrize("tree,flat", zip(FILE_TREES, FLAT_FILE_TREES))
def test_flatten_tree(tree, flat):
    """
    We can flatten a tree!
    """
    assert FileTree.flatten_tree(tree) == flat


@pytest.mark.parametrize("tree,flat", zip(FILE_TREES, FLAT_FILE_TREES))
def test_unflatten_tree(tree, flat):
    """
    We can unflatten a tree!
    """
    assert FileTree.unflatten_tree(flat) == tree


@pytest.mark.parametrize("tree,flat", zip(FILE_TREES, FLAT_FILE_TREES))
def test_roundtrip_tree(tree, flat):
    """
    We can roundtrip flatten and unflattening trees!
    """
    assert FileTree.unflatten_tree(FileTree.flatten_tree(tree)) == tree
    assert FileTree.flatten_tree(FileTree.unflatten_tree(flat)) == flat
