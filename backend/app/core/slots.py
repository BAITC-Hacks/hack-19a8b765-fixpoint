from datetime import date
import re

def validate_slots(values, catalog):
    clean, invalid = {}, []
    for key, value in values.items():
        spec = catalog.slots.get(key)
        if not spec or value is None:
            continue
        try:
            kind = spec['type']
            if kind == 'integer':
                if isinstance(value, bool) or not isinstance(value, (int, str)):
                    raise ValueError()
                value = int(value)
                if value < 0:
                    raise ValueError()
            elif kind == 'boolean':
                if not isinstance(value, bool):
                    raise ValueError()
            elif kind == 'date':
                value = date.fromisoformat(str(value)).isoformat()
            elif kind == 'list':
                if not isinstance(value, list) or not value:
                    raise ValueError()
                value = [str(v).strip() for v in value]
            elif kind == 'enum':
                value = next(v for v in spec['values'] if str(v).lower() == str(value).lower())
            else:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError()
                value = value.strip()
            if key == 'phone':
                value = re.sub(r'[^\d+]', '', value)
                if value.startswith('8') and len(value) == 11:
                    value = '+7' + value[1:]
                if value.startswith('7') and len(value) == 11:
                    value = '+' + value
            if 'pattern' in spec:
                parts = value if isinstance(value, list) else [value]
                if any(not re.fullmatch(spec['pattern'], str(v)) for v in parts):
                    raise ValueError()
            clean[key] = value
        except (ValueError, TypeError, StopIteration):
            invalid.append(key)
    return clean, invalid
