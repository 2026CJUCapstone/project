"""Small dependency-free request media-type checks used before body reads."""


def is_utf8_json_content_type(values: list[str]) -> bool:
    """Accept one application/json value and reject malformed/non-UTF-8 forms."""
    if len(values) != 1:
        return False
    media_type, separator, parameters = values[0].partition(';')
    if media_type.strip().lower() != 'application/json':
        return False
    if not separator:
        return True
    for parameter in parameters.split(';'):
        name, equals, value = parameter.partition('=')
        if not equals or not name.strip() or not value.strip():
            return False
        if name.strip().lower() == 'charset' and value.strip().strip('"\'').lower() not in ('utf-8', 'utf8'):
            return False
    return True
