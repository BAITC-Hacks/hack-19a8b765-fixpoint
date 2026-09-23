"""Conservative extraction of spoken 12-digit IIN/ЖСН identifiers.

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
