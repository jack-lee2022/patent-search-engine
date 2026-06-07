import sys
import json

def generate_claim_chart(patent_id, claims_text, product_description):
    """
    此腳本由 AI Agent 調用，利用 LLM 進行權利要求特徵拆解與對標。
    """
    print(f"[ANALYSIS] 正在解析專利 {patent_id} 的權利要求...")
    
    # 這裡的邏輯是模擬將文本傳送給 LLM 進行結構化處理
    # 在實際 Agent 運行中，Agent 會直接讀取此腳本的輸出並填充內容
    
    prompt = f"""
    任務：將專利 {patent_id} 的獨立權利要求拆解為技術特徵元件 (Elements)，並與產品技術進行比對。
    
    專利權利要求內容：
    {claims_text}
    
    產品/目標技術描述：
    {product_description}
    
    請輸出 JSON 格式的 Claim Chart：
    [
        {{"element_id": "1a", "claim_text": "...", "product_matching": "...", "status": "Literal/Equivalent/Non-infringing"}},
        ...
    ]
    """
    
    # 在本腳本中，我們輸出分析模板，Agent 會負責調用其內置 LLM 完成填充
    template = {
        "patent_id": patent_id,
        "status": "Ready for LLM analysis",
        "instruction": "Please parse the provided claims and product description into a standard Claim Chart format."
    }
    
    return json.dumps(template, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python claim_chart_gen.py <patent_id> <product_desc_file>")
        sys.exit(1)
    
    pid = sys.argv[1]
    # 範例邏輯
    print(generate_claim_chart(pid, "Example Claims", "Example Product"))
