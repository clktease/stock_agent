import sys, json, io
sys.path.insert(0, '.')

# Simulate the user's actual CSV
CSV_CONTENT = """代號,數量,價格,變更$,變更%,市值,當日益損$,單位成本,成本,益損$,持倉佔比,益損%
DRAM,35,65.5,0.38,0.58,2292.51,13.31,53.55543,1874.44,418.07,11.20%,22.3
GOOG,6,359.12,2.56,0.72,2154.71,15.35,282.29167,1693.75,460.96,10.52%,27.22
GOOGL,13,360.87,3.1,0.87,4691.31,40.3,334.52462,4348.82,342.49,22.91%,7.88
NVDA,4,205.42,0.55,0.27,821.66,2.18,178.97,715.88,105.78,4.01%,14.78
QQQ,2,722.98,5.86,0.82,1445.96,11.72,618.305,1236.61,209.35,7.06%,16.93
SOXX,2,600.21,13.28,2.26,1200.42,26.56,520.64,1041.28,159.14,5.86%,15.28
TSLA,3,406.1,6.95,1.74,1218.3,20.85,398.92,1196.76,21.54,5.95%,1.8
TSM,6,425.8,4.73,1.12,2554.8,28.38,336.85333,2021.12,533.68,12.48%,26.41
VOO,6,682.68,4.45,0.66,4096.05,26.67,622.17167,3733.03,363.02,20.00%,9.72
"""

# Write temp CSV
with open('test_real_holdings.csv', 'w', encoding='utf-8') as f:
    f.write(CSV_CONTENT)

from skills import read_holdings_csv

result = json.loads(read_holdings_csv.invoke({'file_path': 'test_real_holdings.csv'}))
print('Error?', result.get('error'))
print('Weight source:', result.get('weight_source'))
print('Columns detected:', result.get('columns_detected'))
print()
print(f"{'Ticker':6s}  {'Weight':8s}  {'Expected':10s}  {'Match?'}")
print('-' * 45)

expected = {
    'DRAM': 11.20, 'GOOG': 10.52, 'GOOGL': 22.91,
    'NVDA': 4.01,  'QQQ': 7.06,   'SOXX': 5.86,
    'TSLA': 5.95,  'TSM': 12.48,  'VOO': 20.00,
}
mismatches = []
for h in result.get('holdings', []):
    w = h.get('weight', 0) * 100
    exp = expected.get(h['ticker'], 0)
    ok = abs(w - exp) < 0.5
    print(f"  {h['ticker']:6s}  {w:6.2f}%   {exp:6.2f}%   {'✓' if ok else '✗ MISMATCH'}")
    if not ok:
        mismatches.append(h['ticker'])

assert not result.get('error'), f"read_holdings_csv returned an error: {result.get('error')}"
assert not mismatches, f"Weight mismatch for: {mismatches}"
print("\nAll tests passed!")
