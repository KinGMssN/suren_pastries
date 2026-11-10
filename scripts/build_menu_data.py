"""Build the Suren Pastries menu from Main_menu.csv (single source of truth).

Outputs (regenerate with: python scripts/build_menu_data.py):
  - scripts/menu_data.py  -> MENU_DATA used by scripts/seed.py to fill the DB.
  - public/static/js/menu-variants.js -> window.SUREN_MENU_META, used by the
    menu page to group variant rows into one card and open the Swiggy-style
    customise sheet.

Why variant rows? Checkout only accepts {item_id, qty} and prices every line
from the MenuItem row in the DB, so every priced choice must be its own row:
pizza Small/Large are already two rows in the CSV; Extra Cheese (+20/+30)
and Schezwan (+30) get one extra row per item ("Name + Extra Cheese").
The menu page shows one card per dish name and the sheet picks the row.
No backend change is needed.
"""
import csv
import json
import os
import re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(BASE, "Main_menu.csv")

CATS = {
    "Quickbites": ("Quick Bites", "\U0001f35f"),
    "burgers": ("Burgers", "\U0001f354"),
    "sandwichies": ("Sandwiches", "\U0001f96a"),
    "soups": ("Soups", "\U0001f963"),
    "staters": ("Starters", "\U0001f357"),
    "biryani": ("Biryani", "\U0001f35b"),
    "curries": ("Curries", "\U0001f35b"),
    "fried rice": ("Fried Rice", "\U0001f35a"),
    "noodles": ("Noodles", "\U0001f35c"),
    "pizza": ("Pizza", "\U0001f355"),
    "deserts": ("Desserts", "\U0001f370"),
    "milkshakes": ("Milkshakes", "\U0001f964"),
    "mocktails": ("Mocktails", "\U0001f379"),
}

# category -> (addon label, addon price, addon name suffix)
ADDONS = {
    "Burgers": ("Extra Cheese", 20, " + Extra Cheese"),
    "Sandwiches": ("Extra Cheese", 20, " + Extra Cheese"),
    "Fried Rice": ("Schezwan", 30, " + Schezwan"),
    "Noodles": ("Schezwan", 30, " + Schezwan"),
    "Pizza": ("Extra Cheese", 30, " + Extra Cheese"),
}


def clean(name):
    return re.sub(r"\s+", " ", name.strip())


def main():
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.reader(f) if r and r[0].strip().isdigit()]

    # base items keyed by (category, name); pizza has two rows (small/large)
    base = {}  # (cat, name) -> dict(veg, emoji, sizes list or price)
    order = []
    for r in rows:
        name = clean(r[1])
        price = int(r[2])
        veg_raw = (r[3] or "").strip().lower()
        veg = True if veg_raw == "veg" else (False if veg_raw == "non veg" else None)
        cat_raw = (r[4] or "").strip()
        cat, emoji = CATS[cat_raw]
        size = (r[6] or "").strip().lower() if len(r) > 6 else ""
        key = (cat, name)
        if key not in base:
            base[key] = {"cat": cat, "name": name, "veg": veg, "emoji": emoji,
                         "sizes": [], "price": None}
            order.append(key)
        if cat == "Pizza":
            base[key]["sizes"].append({"label": size.title(), "price": price})
        else:
            base[key]["price"] = price

    menu_data = {}
    meta = {}
    for key in order:
        item = base[key]
        cat, name = key
        rows_out = []
        if cat == "Pizza":
            sizes = sorted(item["sizes"], key=lambda s: s["price"])
            for s in sizes:
                rows_out.append((f"{name} ({s['label']})", s["price"]))
                rows_out.append((f"{name} ({s['label']}) + Extra Cheese",
                                 s["price"] + 30))
            meta[f"{cat} | {name}"] = {
                "veg": item["veg"], "emoji": item["emoji"],
                "sizes": [{"label": s["label"], "price": s["price"],
                           "row": f"{name} ({s['label']})"} for s in sizes],
                "addons": [{"label": "Extra Cheese", "price": 30,
                            "suffix": " + Extra Cheese"}],
            }
        else:
            rows_out.append((name, item["price"]))
            m = {"veg": item["veg"], "emoji": item["emoji"]}
            if cat in ADDONS:
                label, extra, suffix = ADDONS[cat]
                rows_out.append((name + suffix, item["price"] + extra))
                m["addons"] = [{"label": label, "price": extra, "suffix": suffix}]
            meta[f"{cat} | {name}"] = m
        for row_name, row_price in rows_out:
            menu_data.setdefault(cat, []).append({
                "name": row_name, "description": "", "price": row_price,
                "emoji": item["emoji"], "tag": "",
            })

    # scripts/menu_data.py
    with open(os.path.join(BASE, "scripts", "menu_data.py"), "w", encoding="utf-8") as f:
        f.write('"""Menu rows generated from Main_menu.csv by scripts/build_menu_data.py.\n'
                'Do not edit by hand — change the CSV and re-run the builder.\n'
                'Variant rows (size / Extra Cheese / Schezwan) are real priced rows:\n'
                'checkout prices every line from its MenuItem row, so each choice\n'
                'needs its own row. The menu page groups them into one card.\n"""\n\n')
        f.write("MENU_DATA = ")
        f.write(repr(menu_data))
        f.write("\n\nTEAM_DATA = []\n")
    total_rows = sum(len(v) for v in menu_data.values())
    print(f"menu_data.py: {total_rows} rows, {len(meta)} dishes, "
          f"{len(menu_data)} categories")

    # public/static/js/menu-variants.js
    with open(os.path.join(BASE, "public", "static", "js", "menu-variants.js"),
              "w", encoding="utf-8") as f:
        f.write("// Generated from Main_menu.csv by scripts/build_menu_data.py.\n"
                "// One entry per dish shown on the menu. `row` is the exact\n"
                "// MenuItem name in the DB for that choice; the sheet picks it.\n"
                "window.SUREN_MENU_META = ")
        f.write(json.dumps(meta, ensure_ascii=False, indent=2))
        f.write(";\n")
    print(f"menu-variants.js: {len(meta)} dishes")


if __name__ == "__main__":
    main()
