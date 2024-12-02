# 使用 Ubuntu 24.04 作为基础镜像
FROM ubuntu:24.04
# 设置工作目录
WORKDIR /app
# 更新软件包列表
RUN apt-get update -y
# 安装必要的软件包
RUN apt-get install -y \
curl \
unzip \
python3-pip \
python3-venv \
cron \
wget \
fonts-liberation \
libasound2-plugins \
libatk-bridge2.0-0 \
libatk1.0-0 \
libatspi2.0-0 \
libcairo2 \
libcups2 \
libdrm2 \
libgbm1 \
libgtk-3-0 \
libnspr4 \
libnss3 \
libpango-1.0-0 \
libvulkan1 \
libxcomposite1 \
libxdamage1 \
libxext6 \
libxfixes3 \
libxkbcommon0 \
libxrandr2 \
xdg-utils \
&& apt-get clean \
&& rm -rf /var/lib/apt/lists/*
# 安装 Chrome
COPY google-chrome-stable_current_amd64.deb .
RUN dpkg -i google-chrome-stable_current_amd64.deb
# 解决 dpkg 依赖问题
RUN apt-get update -y && apt-get install -f -y
# 下载并配置 ChromeDriver
COPY chromedriver_linux64.zip .
RUN unzip chromedriver_linux64.zip \
&& mv chromedriver-linux64/chromedriver /usr/local/bin/ \
&& chmod +x /usr/local/bin/chromedriver \
&& rm -rf chromedriver-linux64 \
&& rm chromedriver_linux64.zip \
&& rm google-chrome-stable_current_amd64.deb
# 创建虚拟环境
RUN python3 -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"
# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt && rm requirements.txt
# 安装 schedule 库
RUN pip install schedule
# 创建设置 ulimit 的脚本
COPY set_ulimits.sh /app/
RUN chmod +x /app/set_ulimits.sh
# 复制 tvshow_downloader.py
COPY tvshow_downloader.py .
# 复制 movie_downloader.py
COPY movie_downloader.py .
# 复制 actor_nfo.py&episodes_nfo.py
COPY actor_nfo.py .
COPY episodes_nfo.py .
COPY manual_search.py .
COPY settings.py .
COPY tmdb_id.py .
# 复制 app.py
COPY app.py .
# 复制 check_rss.py
COPY check_rss.py .
# 复制 rss.py
COPY rss.py .
# 复制 scan_media.py
COPY scan_media.py .
# 复制 sync.py
COPY sync.py .
# 复制html
COPY templates.zip .
RUN unzip templates.zip -d /app/ \
&& rm templates.zip
# 创建定时任务脚本
COPY main.py .
# 运行定时任务脚本
CMD ["python", "main.py"]
# 声明监听端口
EXPOSE 8888