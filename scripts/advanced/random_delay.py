import time
import random
import numpy as np

def get_random_delay(mu=5.0, sigma=2.0, min_delay=1.0):
    """
    產生一個符合正態分佈 (Normal Distribution) 的隨機延遲時間。
    
    參數:
    - mu: 平均延遲時間 (秒)
    - sigma: 標準差，控制隨機波動程度
    - min_delay: 最小延遲時間，確保不會過快
    """
    delay = np.random.normal(mu, sigma)
    return max(min_delay, delay)

def human_like_sleep(mu=5.0, sigma=2.0):
    """
    執行模擬人類行為的隨機等待。
    """
    delay = get_random_delay(mu, sigma)
    print(f"[THROTTLE] 模擬人類行為中... 等待 {delay:.2f} 秒")
    time.sleep(delay)

if __name__ == "__main__":
    # 測試延遲產生
    for i in range(5):
        print(f"Test {i+1}: {get_random_delay():.2f}s")
