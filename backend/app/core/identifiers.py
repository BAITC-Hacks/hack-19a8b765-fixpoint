"""Conservative extraction of spoken identifiers from RU/KK transcripts.

Only complete sequences are returned. This does not repair missing or uncertain
digits and is deliberately limited to common RU/KK number words.
"""

import re


UNITS = {
    'ноль': 0, 'нуль': 0, 'нөл': 0, 'нол': 0,
    'один': 1, 'одна': 1, 'бір': 1, 'бир': 1,
    'два': 2, 'две': 2, 'екі': 2, 'эки': 2,
    'три': 3, 'үш': 3, 'уч': 3, 'үч': 3,
    'четыре': 4, 'төрт': 4, 'торт': 4,
    'пять': 5, 'бес': 5, 'беш': 5,
    'шесть': 6, 'алты': 6,
    'семь': 7, 'жеті': 7, 'жети': 7,
    'восемь': 8, 'сегіз': 8, 'сегиз': 8,
    'девять': 9, 'тоғыз': 9, 'тогыз': 9, 'тогуз': 9,
}
TEENS = {
    'десять': 10, 'одиннадцать': 11, 'двенадцать': 12, 'тринадцать': 13,
    'четырнадцать': 14, 'пятнадцать': 15, 'шестнадцать': 16,
    'семнадцать': 17, 'восемнадцать': 18, 'девятнадцать': 19,
}
TENS = {
    'двадцать': 20, 'тридцать': 30, 'сорок': 40, 'пятьдесят': 50,
    'шестьдесят': 60, 'семьдесят': 70, 'восемьдесят': 80, 'девяносто': 90,
    'он': 10, 'жиырма': 20, 'отыз': 30, 'қырық': 40, 'елу': 50,
    'алпыс': 60, 'жетпіс': 70, 'сексен': 80, 'тоқсан': 90,
}
HUNDREDS = {
    'сто': 100, 'двести': 200, 'триста': 300, 'четыреста': 400,
    'пятьсот': 500, 'шестьсот': 600, 'семьсот': 700,
    'восемьсот': 800, 'девятьсот': 900,
}
NUMERIC_WORDS = set(UNITS) | set(TEENS) | set(TENS) | set(HUNDREDS) | {'жүз'}
TOKEN = re.compile(r'[0-9]+|[а-яёәғқңөұүһі]+', re.IGNORECASE)
IIN_MARKER = re.compile(r'\b(?:иин|жсн|iin|zhsn)\b', re.IGNORECASE)
PHONE_MARKER = re.compile(r'\b(?:телефон\w*|нөмір\w*|номер телефона|phone)\b', re.IGNORECASE)
PLUS_MARKER = re.compile(r'\+|\b(?:плюс|plus)\b', re.IGNORECASE)
PLATE_MARKER = re.compile(
    r'\b(?:госномер\w*|номер\s+(?:машин\w*|автомобил\w*)|'
    r'көлік\w*\s+нөмір\w*|мемлекеттік\s+нөмір\w*)\b', re.IGNORECASE,
)
POLICY_MARKER = re.compile(r'\b(?:полис\w*|сақтандыру\s+полис\w*)\b', re.IGNORECASE)
CLAIM_MARKER = re.compile(r'\b(?:заявлени\w*|обращени\w*|страхов\w*\s+случа\w*|өтініш\w*)\b', re.IGNORECASE)
PLATE_TOKEN = re.compile(r'[0-9]+|[a-z]+|[а-яёәғқңөұүһі]+', re.IGNORECASE)
CYRILLIC_PLATE_LETTERS = {
    'А': 'A', 'В': 'B', 'Е': 'E', 'К': 'K', 'М': 'M', 'Н': 'H',
    'О': 'O', 'Р': 'P', 'С': 'C', 'Т': 'T', 'У': 'Y', 'Х': 'X',
    'Б': 'B', 'Г': 'G', 'Д': 'D', 'З': 'Z', 'И': 'I', 'Л': 'L',
    'П': 'P', 'Ф': 'F',
}
SPOKEN_PLATE_LETTERS = {
    'ка': 'K', 'кэ': 'K', 'эм': 'M', 'а': 'A', 'бэ': 'B',
    'вэ': 'V', 'гэ': 'G', 'дэ': 'D', 'е': 'E', 'же': 'J',
    'зэ': 'Z', 'и': 'I', 'эль': 'L', 'эн': 'N', 'о': 'O',
    'пэ': 'P', 'эр': 'R', 'эс': 'S', 'тэ': 'T', 'у': 'U',
    'эф': 'F', 'ха': 'H', 'икс': 'X', 'зет': 'Z',
}
POLICY_PRODUCTS = {
    'ogpo': 'OGPO', 'огпо': 'OGPO',
    'casco': 'CASCO', 'каско': 'CASCO',
    'trvl': 'TRVL', 'travel': 'TRVL', 'тревел': 'TRVL',
    'prop': 'PROP', 'ns': 'NS', 'нс': 'NS',
    'dms': 'DMS', 'дмс': 'DMS',
}


def _digits(words):
    result = []
    pos = 0
    while pos < len(words):
        word = words[pos]
        if word.isascii() and word.isdigit():
            result.append(word)
            pos += 1
            continue
        if word in HUNDREDS or word == 'жүз' or (word in UNITS and pos + 1 < len(words) and words[pos + 1] == 'жүз'):
            if word in UNITS:
                value = UNITS[word] * 100
                pos += 2
            else:
                value = HUNDREDS.get(word, 100)
                pos += 1
            if pos < len(words) and words[pos] in TEENS:
                value += TEENS[words[pos]]
                pos += 1
            else:
                if pos < len(words) and words[pos] in TENS:
                    value += TENS[words[pos]]
                    pos += 1
                if pos < len(words) and words[pos] in UNITS and UNITS[words[pos]]:
                    value += UNITS[words[pos]]
                    pos += 1
        elif word in TENS:
            value = TENS[word]
            pos += 1
            if pos < len(words) and words[pos] in UNITS and UNITS[words[pos]]:
                value += UNITS[words[pos]]
                pos += 1
        elif word in TEENS:
            value = TEENS[word]
            pos += 1
        else:
            value = UNITS[word]
            pos += 1
        result.append(str(value))
    return ''.join(result)


def _numeric_runs(text):
    runs = []
    current = []
    for word in TOKEN.findall(text.lower()):
        if (word.isascii() and word.isdigit()) or word in NUMERIC_WORDS:
            current.append(word)
        elif current:
            runs.append(_digits(current))
            current = []
    if current:
        runs.append(_digits(current))
    return runs


def extract_iins(text):
    """Return complete 12-digit runs; never pad or infer an absent digit."""
    found = []
    for run in _numeric_runs(text):
        if len(run) == 12:
            found.append(run)
        elif len(run) in (24, 36):
            found.extend(run[index:index + 12] for index in range(0, len(run), 12))
    return found


def extract_phones(text):
    """Return only complete Kazakhstan numbers supported by the transcript."""
    explicit_plus = bool(PLUS_MARKER.search(text))
    found = []
    for run in _numeric_runs(text):
        if len(run) == 11 and run[0] in ('7', '8'):
            phone = '+7' + run[1:]
        elif len(run) == 10 and run[0] == '7' and not explicit_plus:
            phone = '+7' + run
        else:
            continue
        if phone not in found:
            found.append(phone)
    return found


def _letter_piece(word):
    spoken = SPOKEN_PLATE_LETTERS.get(word.lower())
    if spoken:
        return spoken
    if word.isascii() and word.isalpha() and len(word) <= 5:
        return word.upper()
    token = word.upper()
    if len(token) <= 5 and all(char in CYRILLIC_PLATE_LETTERS for char in token):
        return ''.join(CYRILLIC_PLATE_LETTERS[char] for char in token)
    return None


def _plate_codes(tokens, start):
    codes = []
    code = ''
    for index in range(start, min(start + 3, len(tokens))):
        piece = _letter_piece(tokens[index])
        if piece is None or len(code + piece) > 3:
            break
        code += piece
        if len(code) >= 2:
            codes.append((code, index + 1))
    return codes


def extract_plates(text):
    """Return complete plates only when all three parts appear in the transcript."""
    tokens = PLATE_TOKEN.findall(text.lower())
    found = []
    for start, word in enumerate(tokens):
        if not (word.isdigit() or word in NUMERIC_WORDS):
            continue
        if start and (tokens[start - 1].isdigit() or tokens[start - 1] in NUMERIC_WORDS):
            continue
        end = start
        while end < len(tokens) and (tokens[end].isdigit() or tokens[end] in NUMERIC_WORDS):
            end += 1
        prefix = _digits(tokens[start:end])
        if len(prefix) != 3:
            continue
        for code, after_code in _plate_codes(tokens, end):
            suffix_end = after_code
            while suffix_end < len(tokens) and (tokens[suffix_end].isdigit() or tokens[suffix_end] in NUMERIC_WORDS):
                suffix_end += 1
            suffix = _digits(tokens[after_code:suffix_end]) if suffix_end > after_code else ''
            if len(suffix) == 2:
                plate = prefix + code + suffix
                if plate not in found:
                    found.append(plate)
    return found


def _reference_digits(tokens, start):
    end = start
    while end < len(tokens) and (tokens[end].isdigit() or tokens[end] in NUMERIC_WORDS):
        end += 1
    return _digits(tokens[start:end]) if end > start else ''


def _policy_product(tokens, start):
    if start >= len(tokens):
        return None, start
    direct = POLICY_PRODUCTS.get(tokens[start])
    if direct:
        return direct, start + 1
    code = ''
    for width in range(1, 6):
        if start + width > len(tokens):
            break
        piece = _letter_piece(tokens[start + width - 1])
        if piece is None or len(code + piece) > 5:
            break
        code += piece
        if code.lower() in POLICY_PRODUCTS:
            return POLICY_PRODUCTS[code.lower()], start + width
    return None, start


def extract_policy_numbers(text):
    """Require the SQ prefix, product, and all six policy digits."""
    tokens = PLATE_TOKEN.findall(text.lower())
    found = []
    for index, token in enumerate(tokens):
        if token == 'sq' or tokens[index:index + 2] == ['s', 'q']:
            product_at = index + (1 if token == 'sq' else 2)
        elif token == 'эс' and tokens[index + 1:index + 2] in (['кью'], ['ку']):
            product_at = index + 2
        else:
            continue
        product, number_at = _policy_product(tokens, product_at)
        if not product:
            continue
        digits = _reference_digits(tokens, number_at)
        if len(digits) == 6:
            number = f'SQ-{product}-{digits}'
            if number not in found:
                found.append(number)
    return found


def extract_claim_numbers(text, *, allow_bare=False):
    """Require six claim digits; CL may be supplied by the asked slot."""
    tokens = PLATE_TOKEN.findall(text.lower())
    found = []
    for index, token in enumerate(tokens):
        if token == 'cl' or tokens[index:index + 2] == ['c', 'l']:
            number_at = index + (1 if token == 'cl' else 2)
        elif token == 'си' and tokens[index + 1:index + 2] == ['эл']:
            number_at = index + 2
        else:
            continue
        digits = _reference_digits(tokens, number_at)
        if len(digits) == 6:
            number = 'CL-' + digits
            if number not in found:
                found.append(number)
    if not found and allow_bare:
        runs = [run for run in _numeric_runs(text) if len(run) == 6]
        if len(runs) == 1:
            found.append('CL-' + runs[0])
    return found
