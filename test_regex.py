import re
print(repr(re.sub(r"^\[[^\]]*\]\s*", "", "[thoughtfully, inner monologue] ")))
print(repr(re.sub(r"^\[[^\]]*\]\s*", "", "[alert] ")))
