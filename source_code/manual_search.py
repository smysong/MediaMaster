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
import threading
import configparser

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MediaDownloader:
    def __init__(self, config_path='/config/config.ini'):
        self.config_path = config_path
        self.driver = None
        self.config = {}
        self.activity_time = time.time()  # 记录最后一次活动的时间
        self.timeout = 60  # 超时时间设置为1分钟
        self.timeout_thread = threading.Thread(target=self.check_timeout)
        self.timeout_thread.daemon = True  # 设置为守护线程
        self.timeout_thread.start()
        self.load_config()

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
        config = configparser.ConfigParser()
        try:
            config.read(self.config_path, encoding='utf-8')
            self.config = {
                "login_username": config.get('resources', 'login_username'),
                "login_password": config.get('resources', 'login_password'),
                "preferred_resolution": config.get('resources', 'preferred_resolution'),
                "fallback_resolution": config.get('resources', 'fallback_resolution'),
                "notification_api_key": config.get('notification', 'notification_api_key'),
                "exclude_keywords": config.get('resources', 'exclude_keywords').split(',')
            }
            self.urls = {
                "movie_login_url": config.get('urls', 'movie_login_url'),
                "tv_login_url": config.get('urls', 'tv_login_url'),
                "movie_search_url": config.get('urls', 'movie_search_url'),
                "tv_search_url": config.get('urls', 'tv_search_url')
            }
            logger.info("加载配置文件成功")
        except (FileNotFoundError, configparser.Error) as e:
            logger.error(f"配置文件 {self.config_path} 不存在或格式错误!")
            exit(1)

    def login_movie_site(self, username, password):
        login_url = self.urls['movie_login_url']
        self.driver.get(login_url)
        try:
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.NAME, "username"))
            )
            logger.info("电影站点登录页面加载完成")
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
            logger.info("电影站点登录成功！")
        except TimeoutException:
            logger.error("电影站点登录失败或页面未正确加载，未找到预期元素！")
            self.close_driver()
            raise

    def login_tv_site(self, username, password):
        login_url = self.urls['tv_login_url']
        self.driver.get(login_url)
        try:
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.NAME, "username"))
            )
            logger.info("电视剧站点登录页面加载完成")
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
            logger.info("电视剧站点登录成功！")
        except TimeoutException:
            logger.error("电视剧站点登录失败或页面未正确加载，未找到预期元素！")
            self.close_driver()
            raise

    def search_movie(self, keyword, year=None):
        self.update_activity_time()
        self.setup_webdriver()
        self.login_movie_site(self.config["login_username"], self.config["login_password"])
        self.driver.get(self.urls['movie_search_url'])

        # 创建一个包含所有可能分辨率的列表
        resolutions = [self.config["preferred_resolution"], self.config["fallback_resolution"]]
        # 过滤掉空字符串
        resolutions = [res for res in resolutions if res]

        try:
            # 增加等待时间
            search_box = WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.ID, 'scform_srchtxt'))
            )
            logger.info("搜索框加载完成")

            # 构建搜索查询
            search_query = f"{keyword} {year}" if year else keyword
            search_box.send_keys(search_query)
            search_box.send_keys(Keys.RETURN)
            logger.info("搜索请求发送完成")
            logger.info("等待电影结果")
            time.sleep(5)  # 假设结果5秒内加载完成

            results = []
            list_items = self.driver.find_elements(By.TAG_NAME, 'li')
            for li in list_items:
                try:
                    a_element = li.find_element(By.TAG_NAME, 'a')
                    title_text = a_element.text
                    link = a_element.get_attribute('href')

                    # 匹配分辨率
                    if any(res in title_text for res in resolutions):
                        logger.info(f"发现: {title_text}, Link: {link}")
                        results.append({
                            "title": title_text,
                            "link": link
                        })
                except NoSuchElementException:
                    logger.warning("未找到搜索结果元素")
                    continue

            return results
        except TimeoutException:
            logger.error("搜索框加载超时，未找到预期元素！")
            self.close_driver()
            return []
        except Exception as e:
            logger.error(f"搜索过程中发生未知错误: {e}")
            self.close_driver()
            return []

    def download_movie(self, link, title, year):
        self.update_activity_time()
        self.setup_webdriver()
        self.login_movie_site(self.config["login_username"], self.config["login_password"])
        self.driver.get(link)
        try:
            WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.CLASS_NAME, "cl")))
            logger.info("进入详情页面")
            logger.info("找到匹配电影结果，开始查找种子文件")
            attachment_link = self.driver.find_element(By.PARTIAL_LINK_TEXT, "Torrent")
            attachment_url = attachment_link.get_attribute('href')
            self.download_torrent(attachment_url, title, year)
            return True
        except NoSuchElementException:
            logger.warning("没有找到附件链接。")
            return False
        except Exception as e:
            logger.error(f"下载过程中发生未知错误: {e}")
            self.close_driver()
            return False

    def search_tv_show(self, keyword, year=None):
        self.update_activity_time()
        self.setup_webdriver()
        self.login_tv_site(self.config["login_username"], self.config["login_password"])
        self.driver.get(self.urls['tv_search_url'])

        # 创建一个包含所有可能分辨率的列表
        resolutions = [self.config["preferred_resolution"], self.config["fallback_resolution"]]
        # 过滤掉空字符串
        resolutions = [res for res in resolutions if res]

        try:
            # 增加等待时间
            search_box = WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.ID, 'scform_srchtxt'))
            )
            logger.info("搜索框加载完成")

            # 构建搜索查询
            search_query = f"{keyword} {year}" if year else keyword
            search_box.send_keys(search_query)
            search_box.send_keys(Keys.RETURN)
            logger.info("搜索请求发送完成")
            logger.info("等待电视剧结果")
            time.sleep(5)  # 假设结果5秒内加载完成

            results = []
            list_items = self.driver.find_elements(By.TAG_NAME, 'li')
            for li in list_items:
                try:
                    a_element = li.find_element(By.TAG_NAME, 'a')
                    title_text = a_element.text
                    link = a_element.get_attribute('href')

                    # 匹配分辨率
                    if any(res in title_text for res in resolutions):
                        logger.info(f"发现: {title_text}, Link: {link}")
                        results.append({
                            "title": title_text,
                            "link": link
                        })
                except NoSuchElementException:
                    logger.warning("未找到搜索结果元素")
                    continue

            return results
        except TimeoutException:
            logger.error("搜索框加载超时，未找到预期元素！")
            self.close_driver()
            return []
        except Exception as e:
            logger.error(f"搜索过程中发生未知错误: {e}")
            self.close_driver()
            return []

    def download_tv_show(self, link, title, year):
        self.update_activity_time()
        self.setup_webdriver()
        self.login_tv_site(self.config["login_username"], self.config["login_password"])
        self.driver.get(link)
        try:
            WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.CLASS_NAME, "cl")))
            logger.info("进入详情页面")
            logger.info("找到匹配电视剧结果，开始查找种子文件")
            attachment_link = self.driver.find_element(By.PARTIAL_LINK_TEXT, "torrent")
            attachment_url = attachment_link.get_attribute('href')
            self.download_torrent(attachment_url, title, year)
            return True
        except NoSuchElementException:
            logger.warning("没有找到附件链接。")
            return False
        except Exception as e:
            logger.error(f"下载过程中发生未知错误: {e}")
            self.close_driver()
            return False

    def download_torrent(self, torrent_url, title, year):
        self.driver.get(torrent_url)
        logger.info("开始下载种子文件")
        time.sleep(10)  # 设置等待时间为10秒，等待文件下载完成
        logger.info(f"下载完成: {title}_{year}")
        self.close_driver()  # 下载完成后关闭 WebDriver

    def close_driver(self):
        if self.driver:
            self.driver.quit()
            logger.info("WebDriver关闭完成")
            self.driver = None  # 重置 driver 变量

    def update_activity_time(self):
        self.activity_time = time.time()
        logger.debug("活动时间更新")

    def check_timeout(self):
        while True:
            if time.time() - self.activity_time > self.timeout:
                logger.error("程序超时，超过1分钟没有活动，关闭WebDriver")
                self.close_driver()
                break  # 退出超时检查线程
            time.sleep(10)  # 每10秒检查一次

    def run(self):
        # 读取配置文件中的登录信息
        self.load_config()

        # 检查配置文件中的必要信息是否存在
        if not self.config.get("login_username") or not self.config.get("login_password"):
            logger.error("请编辑配置文件 %s 并填写正确的用户名、密码等参数。", self.config_path)
            exit(1)

if __name__ == "__main__":
    downloader = MediaDownloader()
    downloader.run()
