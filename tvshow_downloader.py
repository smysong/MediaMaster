import sqlite3
import json
import configparser
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
import re
import requests
import shutil

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DOWNLOAD_RECORD_FILE = '/config/tvshow_download_records.json'

class TVDownloader:
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
            with open(DOWNLOAD_RECORD_FILE, 'r', encoding='utf-8') as file:
                records = json.load(file)
                logger.debug("加载下载记录成功")
                return records
        logger.info("下载记录文件不存在，创建新文件")
        return []

    def save_download_records(self, records):
        """保存已下载记录"""
        with open(DOWNLOAD_RECORD_FILE, 'w', encoding='utf-8') as file:
            json.dump(records, file, ensure_ascii=False, indent=4)
            logger.debug("保存下载记录成功")

    def build_record_key(self, item, resolution, title_text):
        # 构建记录键，使用实际的标题
        return f"{item['剧集']}_{resolution}_{title_text}"

    def extract_tv_info(self):
        """从数据库读取缺失的电视节目信息"""
        all_tv_info = []
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT title, missing_episodes FROM MISS_TVS')
            tvs = cursor.fetchall()
            
            for title, missing_episodes_str in tvs:
                missing_episodes = [int(ep.strip()) for ep in missing_episodes_str.split(',') if ep.strip()]
                if missing_episodes:
                    min_episode_num = min(missing_episodes)
                    formatted_episode_number = f'{"0" if min_episode_num < 10 else ""}{min_episode_num}'
                else:
                    formatted_episode_number = '01'  # 如果无缺失集数信息，则认为是从第01集开始缺失
                resolution = self.config.get("resources", {}).get("preferred_resolution", "")
                all_tv_info.append({
                    "剧集": title,
                    "分辨率": resolution,
                    "集数": formatted_episode_number
                })
        logger.debug("读取缺失的电视节目信息完成")
        return all_tv_info

    def find_episode_links(self, list_items, item, resolution):
        found_links = []
        exclude_keywords = self.config.get("resources", {}).get("exclude_keywords", "")
        exclude_keywords = [keyword.strip() for keyword in exclude_keywords.split(',')]
        
        for li in list_items:
            try:
                a_element = li.find_element(By.TAG_NAME, 'a')
                title_text = a_element.text.lower()

                # 检查是否需要排除此条目
                if any(keyword in title_text for keyword in exclude_keywords):
                    continue

                # 匹配集数范围
                range_match = f"[第{item['集数']}-" in title_text
                # 匹配精确集数
                exact_match = f"[第{item['集数']}集]" in title_text
                if resolution.lower() in title_text and (exact_match or range_match):
                    link = a_element.get_attribute('href')
                    found_links.append((link, title_text))
                    logger.info(f"发现: {title_text}, Link: {link}")
            except NoSuchElementException:
                logger.warning("未找到搜索结果元素")
                continue
        return found_links

    def find_full_set_resource(self, resolution, download_records, item):
        list_items = self.driver.find_elements(By.TAG_NAME, 'li')
        for li in list_items:
            try:
                a_element = li.find_element(By.TAG_NAME, 'a')
                title_text = a_element.text.lower()

                # 获取排除关键字列表
                exclude_keywords = self.config.get("resources", {}).get("exclude_keywords", "")
                exclude_keywords = [keyword.strip() for keyword in exclude_keywords.split(',')]
                
                # 检查是否需要排除此条目
                if any(keyword in title_text for keyword in exclude_keywords):
                    continue
                
                # 匹配全集，并且包含分辨率
                if '全' in title_text and any(char.isdigit() for char in title_text) and resolution.lower() in title_text:
                    link = a_element.get_attribute('href')
                    logger.info(f"发现全集资源: {title_text}, Link: {link}")
                    self.handle_full_set(link, item, resolution, download_records)
                    return True
            except NoSuchElementException:
                logger.warning("未找到搜索结果元素")
                continue
        return False

    def search_and_download(self, search_url, items):
        download_records = self.load_download_records()
        
        for item in items:
            # 构建下载记录的键
            preferred_resolution = item.get('分辨率', "")
            fallback_resolution = self.config.get("resources", {}).get("fallback_resolution", "")
            
            # 尝试首选分辨率
            record_key = self.build_record_key(item, preferred_resolution, "未知标题")
            if record_key not in download_records:
                logger.info(f"开始搜索: 剧集 {item['剧集']}, 分辨率 {preferred_resolution}, 集数 {item['集数']}")
                self.driver.get(search_url)
                search_box = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.ID, 'scform_srchtxt'))
                )
                search_box.send_keys(item['剧集'])
                search_box.send_keys(Keys.RETURN)
                logger.info("搜索请求发送完成")
                logger.info("等待剧集结果")
                time.sleep(5)  # 假设结果5秒内加载完成

                # 查找全集资源优先
                full_set_found = self.find_full_set_resource(preferred_resolution, download_records, item)
                if full_set_found:
                    continue
                
                # 没有找到全集资源，按单集搜索
                found_links = self.find_episode_links(self.driver.find_elements(By.TAG_NAME, 'li'), item, preferred_resolution)
                if found_links:
                    self.handle_single_episodes(found_links, item, preferred_resolution, download_records)
                    continue
                
                # 没有找到首选分辨率的资源，尝试次级分辨率
                logger.warning("未找到首选分辨率资源，尝试备选分辨率搜索")
                self.search_with_fallback_resolution(item, search_url, download_records, preferred_resolution, fallback_resolution)
            else:
                logger.debug(f"记录已存在，跳过下载: {record_key}")

    def search_with_fallback_resolution(self, item, search_url, download_records, preferred_resolution, fallback_resolution):
        record_key = self.build_record_key(item, fallback_resolution, "未知标题")
        if record_key not in download_records:
            logger.info(f"开始搜索: 剧集 {item['剧集']}, 分辨率 {fallback_resolution}, 集数 {item['集数']}")
            self.driver.get(search_url)
            search_box = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, 'scform_srchtxt'))
            )
            search_box.send_keys(item['剧集'])
            search_box.send_keys(Keys.RETURN)
            logger.info("搜索请求发送完成")
            logger.info("等待剧集结果")
            time.sleep(5)  # 假设结果5秒内加载完成

            # 查找全集资源优先
            full_set_found = self.find_full_set_resource(fallback_resolution, download_records, item)
            if full_set_found:
                return
            
            # 没有找到全集资源，按单集搜索
            found_links = self.find_episode_links(self.driver.find_elements(By.TAG_NAME, 'li'), item, fallback_resolution)
            if found_links:
                self.handle_single_episodes(found_links, item, fallback_resolution, download_records)
            else:
                logger.warning("没有找到匹配的下载链接。")
        else:
            logger.debug(f"记录已存在，跳过下载: {record_key}")

    def handle_full_set(self, link, item, resolution, download_records):
        # 处理全集资源的方法
        self.driver.get(link)
        WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.CLASS_NAME, "plc")))
        logger.debug("进入详情页面")
        logger.info("找到匹配全集剧集结果，开始查找种子文件")
        
        # 构建记录键
        record_key = self.build_record_key(item, resolution, "全集")
        if record_key in download_records:
            logger.info(f"记录已存在，跳过下载: {record_key}")
            return
        
        try:
            attachment_link = self.driver.find_element(By.PARTIAL_LINK_TEXT, "torrent")
            attachment_url = attachment_link.get_attribute('href')
            self.download_torrent(attachment_url, item, "全集", resolution, download_records)
        except NoSuchElementException:
            logger.warning("没有找到附件链接。")

    def handle_single_episodes(self, found_links, item, resolution, download_records):
        # 处理单集资源的方法
        if found_links:
            # 只处理第一个匹配结果
            first_link, first_title_text = found_links[0]
            # 构建记录键
            record_key = self.build_record_key(item, resolution, first_title_text)
            if record_key in download_records:
                logger.info(f"记录已存在，跳过下载: {record_key}")
                return
            self.driver.get(first_link)
            WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.CLASS_NAME, "plc")))
            logger.debug("进入详情页面")
            logger.info("找到匹配剧集结果，开始查找种子文件")
            try:
                attachment_link = self.driver.find_element(By.PARTIAL_LINK_TEXT, "torrent")
                attachment_url = attachment_link.get_attribute('href')
                self.download_torrent(attachment_url, item, first_title_text, resolution, download_records)
            except NoSuchElementException:
                logger.warning("没有找到附件链接。")
        else:
            logger.warning("没有找到匹配的下载链接。")

    def download_torrent(self, torrent_url, item, title_text, resolution, download_records):
        self.driver.get(torrent_url)
        logger.info("开始下载种子文件")
        time.sleep(10)  # 设置等待时间为10秒，等待文件下载完成
        self.send_notification(item, title_text, resolution)
        
        # 从标题中提取集数范围
        episode_range = self.extract_episode_number(title_text)
        
        # 构建记录键
        record_key = self.build_record_key(item, resolution, title_text)
        if record_key not in download_records:
            download_records.append(record_key)
            self.save_download_records(download_records)
            logger.info(f"下载记录更新完成: {record_key}")
        else:
            logger.info(f"记录已存在，跳过更新: {record_key}")
        
        # 尝试下载下一集
        if episode_range is not None:
            start_episode, end_episode = episode_range
            next_episode_number = str(int(end_episode) + 1).zfill(2)
            logger.info(f"尝试下载下一集：第{next_episode_number}集")
            self.search_and_download_next_episode(item, next_episode_number, resolution)

    def extract_episode_number(self, title_text):
        # 正则表达式匹配集数或集数范围
        episode_pattern = r"(?:第)?(\d{1,2})(?:-(\d{1,2}))?(?:集)?"
        match = re.search(episode_pattern, title_text)
        
        if match:
            start_episode = match.group(1)
            end_episode = match.group(2) or start_episode
            
            # 返回集数范围的元组
            return (start_episode, end_episode)
        else:
            logger.error("无法从标题中提取集数")
            return None

    def search_and_download_next_episode(self, item, next_episode_number, resolution):
        search_url = self.config.get("urls", {}).get("tv_search_url", "")
        search_term = f"{item['剧集']}"
        self.driver.get(search_url)
        search_box = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, 'scform_srchtxt'))
        )
        search_box.send_keys(search_term)
        search_box.send_keys(Keys.RETURN)
        logger.info("搜索请求发送完成")
        logger.info("等待剧集结果")
        time.sleep(5)  # 假设结果5秒内加载完成
        
        # 查找符合的资源
        list_items = self.driver.find_elements(By.TAG_NAME, 'li')
        found_links = []
        exclude_keywords = self.config.get("resources", {}).get("exclude_keywords", "")
        exclude_keywords = [keyword.strip() for keyword in exclude_keywords.split(',')]
        
        for li in list_items:
            try:
                a_element = li.find_element(By.TAG_NAME, 'a')
                title_text = a_element.text.lower()

                # 检查是否需要排除此条目
                if any(keyword in title_text for keyword in exclude_keywords):
                    continue

                # 匹配精确集数
                exact_match = f"[第{next_episode_number}集]" in title_text
                # 匹配集数范围
                range_match = f"[第{next_episode_number}-" in title_text
                if resolution.lower() in title_text and (exact_match or range_match):
                    link = a_element.get_attribute('href')
                    found_links.append((link, title_text))
                    logger.info(f"发现: {title_text}, Link: {link}")
            except NoSuchElementException:
                logger.warning("未找到搜索结果元素")
                continue

        if found_links:
            # 只处理第一个匹配结果
            first_link, first_title_text = found_links[0]
            # 更新记录键为实际的标题
            record_key = self.build_record_key(item, resolution, first_title_text)
            download_records = self.load_download_records()
            if record_key in download_records:
                logger.info(f"记录已存在，跳过下载: {record_key}")
                return
            self.driver.get(first_link)
            WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.CLASS_NAME, "plc")))
            logger.debug("进入详情页面")
            logger.info("找到匹配剧集结果，开始查找种子文件")
            try:
                attachment_link = self.driver.find_element(By.PARTIAL_LINK_TEXT, "torrent")
                attachment_url = attachment_link.get_attribute('href')
                self.download_torrent(attachment_url, item, first_title_text, resolution, download_records)
            except NoSuchElementException:
                logger.warning("没有找到附件链接。")
        else:
            logger.warning("没有找到匹配的下载链接。")

    def send_notification(self, item, title_text, resolution):
        api_key = self.config.get("notification", {}).get("notification_api_key", "")
        if not api_key:
            logger.error("通知API Key未在配置文件中找到，无法发送通知。")
            return
        api_url = f"https://api.day.app/{api_key}"
        data = {
            "title": "下载通知",
            "body": f"{item['剧集']} - {resolution} - {title_text}"  # 使用 title_text 作为 body 内容
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
        
        # 提取电视节目信息
        all_tv_info = self.extract_tv_info()

        # 登录操作
        login_url = self.config.get("urls", {}).get("tv_login_url", "")
        self.login(login_url, self.config["resources"]["login_username"], self.config["resources"]["login_password"])

        # 搜索和下载操作
        search_url = self.config.get("urls", {}).get("tv_search_url", "")
        self.search_and_download(search_url, all_tv_info)

        # 清理工作，关闭浏览器
        self.driver.quit()
        logger.info("WebDriver关闭完成")

if __name__ == "__main__":
    downloader = TVDownloader(config_path='/config/config.ini')
    downloader.run()