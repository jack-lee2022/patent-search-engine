import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

def plot_assignee_trends(data_csv):
    """
    生成申請人趨勢分析圖
    """
    df = pd.read_csv(data_csv)
    plt.figure(figsize=(10, 6))
    # 假設 CSV 有 'assignee' 和 'year' 欄位
    top_assignees = df['assignee'].value_counts().head(10).index
    df_plot = df[df['assignee'].isin(top_assignees)]
    
    sns.countplot(data=df_plot, y='assignee', order=top_assignees)
    plt.title('Top 10 Patent Assignees')
    plt.tight_layout()
    plt.savefig('patent_landscape.png')
    print("[VISUAL] 專利地圖已生成至 patent_landscape.png")

if __name__ == "__main__":
    print("Visualization module ready. Integrate with search_report.py to generate visual charts.")
