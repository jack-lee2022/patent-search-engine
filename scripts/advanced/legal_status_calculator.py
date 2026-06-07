import datetime
import sys

def calculate_expiration(filing_date_str, patent_type="Utility"):
    """
    計算專利預計屆滿日。
    通常為申請日起算 20 年 (發明專利)。
    """
    try:
        filing_date = datetime.datetime.strptime(filing_date_str, "%Y-%m-%d")
        if patent_type == "Utility":
            expiration_date = filing_date.replace(year=filing_date.year + 20)
        else: # Design
            expiration_date = filing_date.replace(year=filing_date.year + 15)
        
        remaining_days = (expiration_date - datetime.datetime.now()).days
        return {
            "expiration_date": expiration_date.strftime("%Y-%m-%d"),
            "remaining_days": max(0, remaining_days),
            "status": "Active" if remaining_days > 0 else "Expired"
        }
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    # 範例執行
    if len(sys.argv) > 1:
        print(calculate_expiration(sys.argv[1]))
    else:
        print("Usage: python legal_status_calculator.py YYYY-MM-DD")
