#!/usr/bin/env python3
"""
Parses cell entries in MCC_MNC_LAC_CID format.
For LTE cells (CID > 65535): extracts eNodeB ID and sector.
    eNodeB = CID >> 8   (28-bit CID, upper 20 bits)
    Sector = CID & 0xFF (lower 8 bits)
"""

ENTRIES = [
    ("00",    "57140", "24756",     "2G/3G"),
    ("26001", "31101", "203296926", "LTE (Plus)"),
    ("26002", "57144", "69398801",  "LTE (T-Mobile)"),
    ("26003", "57144", "43764761",  "LTE (Orange)"),
    ("26003", "57144", "43764791",  "LTE (Orange)"),
    ("2601",  "31961", "222879381", "WCDMA"),
    ("2602",  "57144", "69398801",  "LTE test"),
    ("",      "57140", "46591280",  "LTE (unknown)"),
]

LTE_CID_THRESHOLD = 65535


def decode_cell(mcc_mnc, lac, cid_str, note):
    cid = int(cid_str)
    is_lte = cid > LTE_CID_THRESHOLD

    enodeb = cid >> 8 if is_lte else None
    sector = cid & 0xFF if is_lte else None

    return {
        "mcc_mnc": mcc_mnc or "?",
        "lac": lac,
        "cid": cid,
        "note": note,
        "is_lte": is_lte,
        "enodeb": enodeb,
        "sector": sector,
    }


def main():
    cells = [decode_cell(*e) for e in ENTRIES]

    col_w = [6, 7, 12, 10, 8, 20]
    header = (
        f"{'#':<3} "
        f"{'MCC_MNC':<8} "
        f"{'LAC':<7} "
        f"{'CID':<12} "
        f"{'eNodeB':<10} "
        f"{'Sektor':<8} "
        f"{'Uwagi'}"
    )
    sep = "-" * len(header)

    print(sep)
    print(header)
    print(sep)

    for i, c in enumerate(cells, 1):
        enodeb_str = str(c["enodeb"]) if c["enodeb"] is not None else "-"
        sector_str = str(c["sector"]) if c["sector"] is not None else "-"

        print(
            f"{i:<3} "
            f"{c['mcc_mnc']:<8} "
            f"{c['lac']:<7} "
            f"{c['cid']:<12} "
            f"{enodeb_str:<10} "
            f"{sector_str:<8} "
            f"{c['note']}"
        )

    print(sep)
    print(f"\nLegenda: eNodeB = CID >> 8  |  Sektor = CID & 0xFF  (tylko dla LTE, CID > {LTE_CID_THRESHOLD})\n")


if __name__ == "__main__":
    main()
