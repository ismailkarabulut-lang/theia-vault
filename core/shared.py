import re

# Ortak regex tanımları — message.py ve api.py buradan import eder
_MEM_SAVE_RE   = re.compile(r"bunu hatırla|bunu kaydet|önemli:", re.IGNORECASE)
_MEM_FORGET_RE = re.compile(r"bunu unut|bunu sil memory'den", re.IGNORECASE)
_MEM_VIEW_RE   = re.compile(r"ne hatırlıyorsun", re.IGNORECASE)
_INTENT_RE     = re.compile(
    r"\b(bakacağım|bakarım|bakayım"
    r"|yapacağım|yaparım|yapayım"
    r"|deneyeceğim|denerim|deneyeyim"
    r"|hallederim|halledeceğim"
    r"|araştıracağım|araştırırım"
    r"|düşüneceğim|düşüneyim"
    r"|ekleyeceğim|eklerim"
    r"|yazacağım|yazarım)\b",
    re.IGNORECASE,
)
