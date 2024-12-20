import sqlite3
import json
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import logging
import os
import time
import requests
import shutil
import configparser

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DOWNLOAD_RECORD_FILE = '/config/movie_download_records.json'

class MovieDownloader:
    def __init__(self, config_path='/config/config.ini'):
        self.config_path = config_path
        self.driver = None
        self.config = {}
        self.db_path = None  # 初始值为None，将在load_config中设置

    def setup_webdriver(self):
        options = Options()
        options.add_argument('--headless')  # 无头模式运行
        options.add_argument('--no-sandbox')  # 在非root用户下需要禁用沙盒
        options.add_argument('--disable-dev-shm-usage')  # 解决/dev/shm空间不足的问题
        options.add_argument('--window-size=1920x1080')  # 设置窗口大小
        
        # 设置默认下载目录
        prefs = {
            "download.default_directory": "/Torrent",
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True
        }
        options.add_experimental_option("prefs", prefs)

        # 指定 chromedriver 的路径
        service = Service(executable_path='/usr/local/bin/chromedriver')
        
        try:
            self.driver = webdriver.Chrome(service=service, options=options)
            logging.info("WebDriver初始化完成")
        except Exception as e:
            logging.error(f"WebDriver初始化失败: {e}")
            raise

    def load_config(self):
        """从INI文件中加载配置"""
        try:
            config = configparser.ConfigParser()
            config.read(self.config_path, encoding='utf-8')
            self.config = {section: dict(config.items(section)) for section in config.sections()}
            
            # 从配置文件中读取数据库路径
            self.db_path = self.config.get('database', {}).get('db_path', '')
            
            logger.debug("加载配置文件成功")
            return self.config
        except FileNotFoundError:
            logger.error(f"配置文件 {self.config_path} 不存在!")
            exit(1)
        except configparser.Error as e:
            logger.error(f"配置文件解析错误: {e}")
            exit(1)

    def login(self, url, username, password):
        self.driver.get(url)
        try:
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.NAME, "username"))
            )
            logger.debug("登录页面加载完成")
            username_input = self.driver.find_element(By.NAME, 'username')
            password_input = self.driver.find_element(By.NAME, 'password')
            username_input.send_keys(username)
            password_input.send_keys(password)
            submit_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.NAME, 'loginsubmit'))
            )
            submit_button.click()
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.PARTIAL_LINK_TEXT, '跳转'))
            )
            logger.info("登录成功！")
        except TimeoutException:
            logger.error("登录失败或页面未正确加载，未找到预期元素！")
            self.driver.quit()
            exit(1)

    def load_download_records(self):
        """加载已下载记录"""
        if os.path.exists(DOWNLOAD_RECORD_FILE):
            try:
                with open(DOWNLOAD_RECORD_FILE, 'r', encoding='utf-8') as file:
                    records = json.load(file)
                    logger.debug("加载下载记录成功")
                    return records
            except Exception as e:
                logger.error(f"加载下载记录时发生错误: {e}")
                return []
        logger.info("下载记录文件不存在，创建新文件")
        return []

    def save_download_records(self, records):
        """保存已下载记录"""
        try:
            with open(DOWNLOAD_RECORD_FILE, 'w', encoding='utf-8') as file:
                json.dump(records, file, ensure_ascii=False, indent=4)
                logger.debug("保存下载记录成功")
        except Exception as e:
            logger.error(f"保存下载记录时发生错误: {e}")

    def extract_movie_info(self):
        """从数据库读取订阅电影信息"""
        all_movie_info = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT title, year FROM MISS_MOVIES')
                movies = cursor.fetchall()
                for title, year in movies:
                    all_movie_info.append({
                        "标题": title,
                        "年份": year
                    })
            logger.debug("读取订阅电影信息完成")
            return all_movie_info
        except Exception as e:
            logger.error(f"提取电影信息时发生错误: {e}")
            return []

    def search_and_download(self, search_url, items):
        download_records = self.load_download_records()

        for item in items:
            # 构建下载记录的键
            record_key = f"{item['标题']}_{item['年份']}"

            if record_key in download_records:
                logger.info(f"记录已存在，跳过下载: {record_key}")
                continue

            logger.info(f"开始搜索: 标题 {item['标题']}, 年份 {item['年份']}")
            self.driver.get(search_url)
            search_box = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, 'scform_srchtxt'))
            )
            search_box.send_keys(f"{item['标题']}")
            search_box.send_keys(Keys.RETURN)
            logger.info("搜索请求发送完成")
            logger.info("等待电影结果")
            time.sleep(5)  # 假设结果5秒内加载完成

            # 查找所有可能的分辨率链接
            list_items = self.driver.find_elements(By.TAG_NAME, 'li')
            found_links = False
            exclude_keywords = self.config.get("resources", {}).get("exclude_keywords", "")
            exclude_keywords = [keyword.strip() for keyword in exclude_keywords.split(',')]

            for li in list_items:
                try:
                    a_element = li.find_element(By.TAG_NAME, 'a')
                    title_text = a_element.text.lower()
                    link = a_element.get_attribute('href')

                    # 检查是否需要排除此条目
                    if any(keyword in title_text for keyword in exclude_keywords):
                        logger.debug(f"排除资源: {title_text}")
                        continue

                    # 从配置文件中获取首选分辨率和备用分辨率
                    preferred_resolution = self.config.get("resources", {}).get("preferred_resolution", "")
                    fallback_resolution = self.config.get("resources", {}).get("fallback_resolution", "")
                    # 创建一个包含所有可能分辨率的列表
                    resolutions = [preferred_resolution, fallback_resolution]
                    # 过滤掉空字符串
                    resolutions = [res for res in resolutions if res]
                    # 检查标题文本中是否包含任何分辨率，并且年份是否匹配
                    if any(res in title_text for res in resolutions) and str(item['年份']) in title_text:
                        logger.info(f"发现: {title_text}, Link: {link}")
                        self.driver.get(link)
                        WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.CLASS_NAME, "cl")))
                        logger.debug("进入详情页面")
                        logger.info("找到匹配电影结果，开始查找种子文件")
                        try:
                            attachment_link = self.driver.find_element(By.PARTIAL_LINK_TEXT, "Torrent")
                            attachment_url = attachment_link.get_attribute('href')
                            self.download_torrent(attachment_url, item, title_text)
                            found_links = True
                            break  # 成功下载后跳出循环
                        except NoSuchElementException:
                            logger.warning("没有找到附件链接。")
                except NoSuchElementException:
                    logger.warning("未找到搜索结果元素")
                    continue

            if not found_links:
                logger.warning(f"没有找到首选和备用分辨率匹配的下载链接。")

    def download_torrent(self, torrent_url, item, title_text):
        self.driver.get(torrent_url)
        logger.info("开始下载种子文件")
        time.sleep(10)  # 设置等待时间为10秒，等待文件下载完成
        self.send_notification(item, title_text)
        # 更新下载记录
        download_records = self.load_download_records()
        download_records.append(f"{item['标题']}_{item['年份']}")  # 只记录电影名称和年份
        self.save_download_records(download_records)
        logger.debug(f"下载记录更新完成: {item['标题']}_{item['年份']}")

    def send_notification(self, item, title_text):
        api_key = self.config.get("notification", {}).get("notification_api_key", "")
        if not api_key:
            logger.error("通知API Key未在配置文件中找到，无法发送通知。")
            return
        api_url = f"https://api.day.app/{api_key}"
        data = {
            "title": "下载通知",
            "body": title_text  # 使用 title_text 作为 body 内容
        }
        headers = {'Content-Type': 'application/json'}
        response = requests.post(api_url, data=json.dumps(data), headers=headers)
        if response.status_code == 200:
            logger.info("通知发送成功: %s", response.text)
        else:
            logger.error("通知发送失败: %s %s", response.status_code, response.text)

    def run(self):
        # 加载配置文件
        self.load_config()
        
        # 检查配置文件中的必要信息是否存在
        if not self.config.get("resources", {}).get("login_username") or \
           not self.config.get("resources", {}).get("login_password") or \
           not self.config.get("notification", {}).get("notification_api_key"):
            logger.error("请编辑配置文件 %s 并填写正确的用户名、密码及API key等参数。", self.config_path)
            exit(1)  # 提示后立即退出程序

        # 初始化WebDriver
        self.setup_webdriver()
        
        # 提取电影信息
        all_movie_info = self.extract_movie_info()

        # 登录操作
        login_url = self.config.get("urls", {}).get("movie_login_url", "")
        self.login(login_url, self.config["resources"]["login_username"], self.config["resources"]["login_password"])

        # 搜索和下载操作
        search_url = self.config.get("urls", {}).get("movie_search_url", "")
        self.search_and_download(search_url, all_movie_info)

        # 清理工作，关闭浏览器
        self.driver.quit()
        logger.info("WebDriver关闭完成")

if __name__ == "__main__":
    downloader = MovieDownloader(config_path='/config/config.ini')
    downloader.run()
