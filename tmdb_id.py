import os
import re
import sqlite3
import xml.etree.ElementTree as ET
import logging
import configparser

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s', encoding='utf-8')

def read_config(config_file):
    """从配置文件中读取信息"""
    config = configparser.ConfigParser()
    config.read(config_file)
    return config

def parse_nfo(file_path):
    """解析NFO文件，返回title, year和tmdb id"""
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
        
        # 查找<title>元素
        title_element = root.find('title')
        title = title_element.text if title_element is not None else None
        
        # 查找<year>元素
        year_element = root.find('year')
        year = year_element.text if year_element is not None else None
        
        # 查找<uniqueid type="tmdb">元素
        tmdb_id_element = root.find(".//uniqueid[@type='tmdb']")
        tmdb_id = tmdb_id_element.text if tmdb_id_element is not None else None
        
        return title, year, tmdb_id
    except Exception as e:
        logging.error(f"解析 {file_path} 时出错: {e}")
        return None, None, None

def find_and_parse_nfo_files(directory, pattern):
    """在给定目录中查找符合模式的NFO文件并解析它们"""
    results = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.nfo') and pattern.match(file):
                file_path = os.path.join(root, file)
                title, year, tmdb_id = parse_nfo(file_path)
                if title and year and tmdb_id:
                    results.append((file, title, year, tmdb_id))
    return results

def update_database(db_path, table, title, year, tmdb_id):
    """更新数据库中的tmdb_id字段"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 检查是否存在tmdb_id字段，如果不存在则创建
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [column[1] for column in cursor.fetchall()]
    if 'tmdb_id' not in columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN tmdb_id TEXT")
        logging.info(f"在表 {table} 中添加了 tmdb_id 字段")
    
    # 查询是否存在相同的title和year
    cursor.execute(f"SELECT * FROM {table} WHERE title = ? AND year = ? AND tmdb_id = ?", (title, year, tmdb_id))
    row = cursor.fetchone()
    
    if row:
        logging.debug(f"跳过处理：表 {table} 中已存在标题 '{title}'，年份 '{year}' 和 tmdb_id '{tmdb_id}'")
    else:
        # 查询是否存在相同的title和year
        cursor.execute(f"SELECT * FROM {table} WHERE title = ? AND year = ?", (title, year))
        row = cursor.fetchone()
        
        if row:
            # 更新tmdb_id字段
            cursor.execute(f"UPDATE {table} SET tmdb_id = ? WHERE title = ? AND year = ?", (tmdb_id, title, year))
            conn.commit()
            logging.info(f"更新了表 {table} 中的标题 '{title}'，年份 '{year}'，tmdb_id 为 '{tmdb_id}'")
        else:
            logging.info(f"在表 {table} 中未找到标题 '{title}' 和年份 '{year}'")
    
    conn.close()

# 从配置文件中读取路径信息
config = read_config('/config/config.ini')
db_path = config['database']['db_path']
movies_path = config['mediadir']['movies_path']
episodes_path = config['mediadir']['episodes_path']

# 定义电影和电视剧的文件命名模式
movie_pattern = re.compile(r'^.* - \(\d{4}\) \d+p\.nfo$')
episode_pattern = re.compile(r'^tvshow\.nfo$')

# 查找并解析电影NFO文件
movie_results = find_and_parse_nfo_files(movies_path, movie_pattern)

# 查找并解析电视剧NFO文件
episode_results = find_and_parse_nfo_files(episodes_path, episode_pattern)

# 更新数据库中的电影记录
for _, title, year, tmdb_id in movie_results:
    update_database(db_path, 'LIB_MOVIES', title, year, tmdb_id)

# 更新数据库中的电视剧记录
for _, title, year, tmdb_id in episode_results:
    update_database(db_path, 'LIB_TVS', title, year, tmdb_id)