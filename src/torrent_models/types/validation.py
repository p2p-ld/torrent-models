from typing import Literal, TypedDict


class ValidationContext(TypedDict, total=False):
    """
    Validation Context parameters that affect validation behavior

    Validation behavior can be controlled like this:

    ```python
    Torrent.model_validate(data, context={"padding": "default"})
    ```

    with any of the values described in this typed dict.

    This model is primarily used for documentation,
    because there is not a valid way that i am aware of to annotate the ValidationInfo.context
    dict since it is read-only (so cast can't be used),
    and one can't annotate non-self attributes.
    plz PR if you know how to get mypy to validate with this type.

    References:
        https://docs.pydantic.dev/latest/concepts/validators/#validation-context
    """

    padding: Literal["default", "ignore", "strict", "forbid"]
    """
    Control how padfiles are validated
    
    `'default`': v1-only torrents -> ignore
                 Hybrid torrents -> strict
    `'ignore'`: skip all padfile validation.
    `'strict'`: every file must start at a piece boundary.
    `'forbid'`: no padfiles may be present.

    if we are validating in pydantic's `strict` mode,
    - `'ignore'` is ignored: strict means that the torrent must be as correct as it can be
    - `'strict'` is unchanged, and becomes the default
    - `'forbid'` is unchanged for v1-only: it's strictly valid to forbid padfiles,
      but for hybrid torrents becomes an error: hybrid torrents *must* be padded
      and the padding must be correct.
    """
    padding_path: Literal["default", "strict"]
    """
    BEP0047 recommends that padfiles are named `.pad/{length}`:
    
    > While clients implementing this extensions will have no use for the path of a padding file 
    > it should be included for backwards compatibility since it is a mandatory field in BEP 3.
    > The recommended path is [".pad", "N"] where N is the length of the padding file in base10. 
    > This way clients not aware of this extension will write the padding files 
    > into a single directory, 
    > potentially re-using padding files from other torrents also stored in that directory.
    
    However this is not required, and is often violated. 
    BEP0047 also recommends now requiring `path` at all for padfiles:
    
    > To eventually allow the path field to be omitted clients implementing this BEP 
    > should not require it to be present on padding files.
    
    So the default behavior is to not check the padfile names,
    but passing `strict` here validates they are `[".pad", length]`
    
    References:
        https://www.bittorrent.org/beps/bep_0047.html
    """
