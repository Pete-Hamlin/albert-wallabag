import json
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from time import sleep
from urllib import parse

import requests
from albert import *

md_iid = "2.1"
md_version = "2.0"
md_name = "Wallabag"
md_description = "Manage saved articles via a wallabag instance"
md_license = "MIT"
md_url = "https://github.com/Pete-Hamlin/albert-python"
md_maintainers = ["@Pete-Hamlin"]
md_lib_dependencies = ["requests"]


class Plugin(PluginInstance, GlobalQueryHandler, TriggerQueryHandler):
    iconUrls = [f"file:{Path(__file__).parent}/wallabag.png"]
    limit = 50
    user_agent = "org.albert.wallabag"

    def __init__(self):
        TriggerQueryHandler.__init__(
            self,
            id=md_id,
            name=md_name,
            description=md_description,
            synopsis="<article-name>",
            defaultTrigger="wb ",
        )
        GlobalQueryHandler.__init__(self, id=md_id, name=md_name, description=md_description, defaultTrigger="wb ")
        PluginInstance.__init__(self, extensions=[self])

        self._instance_url = self.readConfig("instance_url", str) or "http://localhost:80"
        self._username = self.readConfig("username", str) or ""
        self._password = self.readConfig("password", str) or ""
        self._client_id = self.readConfig("client_id", str) or ""
        self._client_secret = self.readConfig("client_secret", str) or ""

        self._cache_results = self.readConfig("cache_results", bool) or True
        self._cache_length = self.readConfig("cache_length", int) or 60
        self._auto_cache = self.readConfig("auto_cache", bool) or False

        self.cache_timeout = datetime.now()
        self.cache_file = self.cacheLocation / "wallabag.json"
        self.thread_stop = Event()
        self.cache_thread = Thread(target=self.cache_routine, daemon=True)

        if not self._auto_cache:
            self.thread_stop.set()

        self.token = None

        self.cache_thread.start()

    @property
    def instance_url(self):
        return self._instance_url

    @instance_url.setter
    def instance_url(self, value):
        self._instance_url = value
        self.writeConfig("instance_url", value)

    @property
    def username(self):
        return self._username

    @username.setter
    def username(self, value):
        self._username = value
        self.writeConfig("username", value)

    @property
    def password(self):
        return self._password

    @password.setter
    def password(self, value):
        self._password = value
        self.writeConfig("password", value)

    @property
    def client_id(self):
        return self._client_id

    @client_id.setter
    def client_id(self, value):
        self._client_id = value
        self.writeConfig("client_id", value)

    @property
    def client_secret(self):
        return self._client_secret

    @client_secret.setter
    def client_secret(self, value):
        self._client_secret = value
        self.writeConfig("client_secret", value)

    @property
    def cache_results(self):
        return self._cache_results

    @cache_results.setter
    def cache_results(self, value):
        self._cache_results = value
        if not self._cache_results:
            # Cleanup cache file
            self.cache_file.unlink(missing_ok=True)
        self.writeConfig("cache_results", value)

    @property
    def cache_length(self):
        return self._cache_length

    @cache_length.setter
    def cache_length(self, value):
        self._cache_length = value
        self.cache_timeout = datetime.now()
        self.writeConfig("cache_length", value)

    @property
    def auto_cache(self):
        return self._auto_cache

    @auto_cache.setter
    def auto_cache(self, value):
        self._auto_cache = value
        if self._auto_cache and self._cache_results:
            self.thread_stop.clear()
        else:
            self.thread_stop.set()
        self.writeConfig("auto_cache", value)

    def configWidget(self):
        return [
            {"type": "lineedit", "property": "instance_url", "label": "URL"},
            {"type": "lineedit", "property": "username", "label": "Username"},
            {
                "type": "lineedit",
                "property": "password",
                "label": "Password",
                "widget_properties": {"echoMode": "Password"},
            },
            {"type": "lineedit", "property": "client_id", "label": "Client ID"},
            {
                "type": "lineedit",
                "property": "client_secret",
                "label": "Client Secret",
                "widget_properties": {"echoMode": "Password"},
            },
            {"type": "checkbox", "property": "cache_results", "label": "Cache results locally"},
            {"type": "spinbox", "property": "cache_length", "label": "Cache length (minutes)"},
            {"type": "checkbox", "property": "auto_cache", "label": "Periodically cache articles"},
        ]

    def handleTriggerQuery(self, query):
        stripped = query.string.strip()
        if stripped:
            # avoid spamming server
            for _ in range(50):
                sleep(0.01)
                if not query.isValid:
                    return

            data = self.get_results()
            articles = (item for item in data if stripped in self.create_filters(item))
            items = [item for item in self.gen_items(articles)]
            query.add(items)
        else:
            query.add(
                StandardItem(
                    id=md_id, text=md_name, subtext="Search for an article saved via Wallabag", iconUrls=self.iconUrls
                )
            )
            if self._cache_results:
                query.add(
                    StandardItem(
                        id=md_id,
                        text="Refresh cache",
                        subtext="Refresh cached articles",
                        iconUrls=["xdg:view-refresh"],
                        actions=[Action("refresh", "Refresh Wallabag cache", lambda: self.refresh_cache())],
                    )
                )

    def handleGlobalQuery(self, query):
        stripped = query.string.strip()
        if stripped and self.cache_file.is_file():
            # If we have results cached display these, otherwise disregard (we don't want to make fetch requests in the global query)
            data = (item for item in self.read_cache())
            articles = (item for item in data if stripped in self.create_filters(item))
            items = [RankItem(item=item, score=0) for item in self.gen_items(articles)]
            return items

    def create_filters(self, item: dict):
        # TODO: Add filter options?
        return ",".join([item["url"], item["title"].lower(), ",".join(tag["label"] for tag in item["tags"])])

    def gen_items(self, articles: object):
        for article in articles:
            yield StandardItem(
                id=md_id,
                text=article["title"] or article["url"],
                subtext="{}".format(",".join(tag["label"] for tag in article["tags"])),
                iconUrls=self.iconUrls,
                actions=[
                    Action("open-url", "Open article URL", lambda u=article["url"]: openUrl(u)),
                    Action(
                        "open",
                        "Open article in wallabag",
                        lambda u="{}/view/{}".format(self._instance_url, article["id"]): openUrl(u),
                    ),
                    Action("copy", "Copy URL to clipboard", lambda u=article["url"]: setClipboardText(u)),
                ],
            )

    def get_results(self):
        if self._cache_results:
            return self._get_cached_results()
        return self.fetch_results()

    def fetch_results(self):
        headers = {"User-Agent": self.user_agent, "Authorization": f"Bearer {self.get_token()}"}
        return (article for article_list in self.get_articles(headers) for article in article_list)

    def get_articles(self, headers: dict):
        # Set the initial pages so the loop runs at least once
        page, pages = 0, 1
        while page < pages:
            page += 1
            params = {"perPage": self.limit, "page": page}
            url = f"{self._instance_url}/api/entries.json?{parse.urlencode(params)}"
            response = requests.get(url, headers=headers, timeout=5)
            if response.ok:
                result = response.json()
                pages = int(result["pages"])
                yield result["_embedded"]["items"]
            else:
                warning(f"Got response {response.status_code} querying {url}")

    def _get_cached_results(self):
        if self.cache_file.is_file() and self.cache_timeout >= datetime.now():
            debug("Cache hit")
            results = self.read_cache()
            return (item for item in results)
        # Cache miss
        debug("Cache miss")
        return self.refresh_cache()

    def cache_routine(self):
        while True:
            if not self.thread_stop.is_set():
                self.refresh_cache()
            sleep(3600)

    def refresh_cache(self):
        results = self.fetch_results()
        self.cache_timeout = datetime.now() + timedelta(minutes=self._cache_length)
        return self.write_cache([item for item in results])

    def read_cache(self):
        with self.cache_file.open("r") as cache:
            return json.load(cache)

    def write_cache(self, data: list[dict]):
        with self.cache_file.open("w") as cache:
            cache.write(json.dumps(data))
        return (item for item in data)

    def get_token(self):
        if not self.token or not self.token.is_valid():
            self.refresh_token()
        return self.token.access

    def refresh_token(self):
        url = f"{self._instance_url}/oauth/v2/token"
        debug(f"Fetching token from {url}")
        response = requests.post(
            url,
            data={
                "grant_type": "password",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "username": self._username,
                "password": self._password,
            },
            timeout=5,
        )
        if response.ok:
            self.token = Token(response.json())
        else:
            warning(f"Got response: {response.status_code} {response.content}")


class Token:
    def __init__(self, token: dict):
        self.access = token["access_token"]
        self.refresh = token["refresh_token"]
        self._expiry = datetime.now() + timedelta(seconds=(token["expires_in"] / 2))

    def is_valid(self):
        return self._expiry <= datetime.now()
