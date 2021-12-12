from glob import glob
from os import path

translation = {}

# this might be slower but formatting dictionaries is such a pain
for csv in glob(path.join("translations", "*.csv")):
    with open(csv) as f:
        locale,_ = path.splitext(path.split(csv)[1])
        strings = translation[locale] = {}
        line_number = 0

        for line in f:
            line_number += 1
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            try:
                ctx, en, tr, *_ = line.split(";")
                strings[ctx.rstrip(), en.strip()] = tr.strip()
            except ValueError:
                print(f"Pribambase translation '{locale}' format error at line {line_number}:\n\t{line}")
