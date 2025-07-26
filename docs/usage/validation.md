# Validation

## Strict mode

By default, `torrent-models` attempts to treat torrent files as an open format,
allowing extra attributes, and only enforcing correctness according to existing BEP specifications
necessary for the torrent to work.

Various parts of the validation process can be made more strict by using pydantic's
[strict mode](https://docs.pydantic.dev/latest/concepts/strict_mode),
either passing `strict=True` to {method}`~pydantic.BaseModel.model_validate`,
or annotating the model with `Annotated[Torrent, pydantic.Strict()]`.

- If padfiles are present, all files must be padded to piece boundaries
  (the `strict` mode for `padding` in validation context, below)
- Padfiles must be named such that their path is `.pad/{size}`.
- (raise an issue if you want more strict behavior!)

## Control via Validation Context

The behavior of validation can be modified using pydantic's
[validation context](https://docs.pydantic.dev/latest/concepts/validators/#validation-context).

```{eval-rst}
.. autoclass:: torrent_models.types.validation.ValidationContext
    :members:
```