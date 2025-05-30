from datetime import datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from time import perf_counter_ns
from urllib import parse

import requests
from albert import *

md_iid = "3.0"
md_version = "3.5"
md_name = "Wallabag"
md_description = "Manage saved articles via a wallabag instance"
md_license = "MIT"
md_url = "https://github.com/Pete-Hamlin/albert-python"
md_authors = ["@Pete-Hamlin"]
md_lib_dependencies = ["requests"]


class ArticleFetcherThread(Thread):
    def __init__(self, callback, cache_length, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.__stop_event = Event()
        self.__callback = callback
        self.__cache_length = cache_length * 60

    def run(self):
        self.__callback()
        while True:
            self.__stop_event.wait(self.__cache_length)
            if self.__stop_event.is_set():
                return
            self.__callback()

    def stop(self):
        self.__stop_event.set()


class Plugin(PluginInstance, IndexQueryHandler):
    iconUrls = [f"file:{Path(__file__).parent}/wallabag.png"]
    limit = 250
    user_agent = "org.albert.wallabag"

    def __init__(self):
        PluginInstance.__init__(self)
        IndexQueryHandler.__init__(self)

        self._index_items = []

        self._instance_url = self.readConfig("instance_url", str) or "http://localhost:80"
        self._username = self.readConfig("username", str) or ""
        self._password = self.readConfig("password", str) or ""
        self._client_id = self.readConfig("client_id", str) or ""
        self._client_secret = self.readConfig("client_secret", str) or ""

        self._cache_length = self.readConfig("cache_length", int) or 15

        self._token = None

        self._thread = ArticleFetcherThread(callback=self.fetchIndexItems, cache_length=self._cache_length)
        self._thread.start()

    def __del__(self):
        self._thread.stop()
        self._thread.join()


    def defaultTrigger(self):
        return "wb "

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
    def cache_length(self):
        return self._cache_length

    @cache_length.setter
    def cache_length(self, value):
        value = 1 if value < 1 else value
        self._cache_length = value
        self.writeConfig("cache_length", value)

        if self._thread.is_alive():
            self._thread.stop()
            self._thread.join()
        self._thread = ArticleFetcherThread(callback=self.updateIndexItems, cache_length=self._cache_length)
        self._thread.start()

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
            {"type": "spinbox", "property": "cache_length", "label": "Cache length (minutes)"},
        ]


    def updateIndexItems(self):
        self.setIndexItems(self._index_items)

    def fetchIndexItems(self):
        start = perf_counter_ns()
        data = self._fetch_results()
        for article in data:
            filter = self._create_filters(article)
            item = self._gen_item(article)
            self._index_items.append(IndexItem(item=item, string=filter))
        self.updateIndexItems()
        info("Indexed {} articles [{:d} ms]".format(len(self._index_items), (int(perf_counter_ns() - start) // 1000000)))
        self._index_items = []

    def handleTriggerQuery(self, query):
        stripped = query.string.strip()
        if stripped:
            TriggerQueryHandler.handleTriggerQuery(self, query)
        else:
            query.add(
                StandardItem(
                    text=md_name, subtext="Search for an article saved in Wallabag", iconUrls=self.iconUrls
                )
            )
        query.add(
            StandardItem(
                text="Refresh cache",
                subtext="Refresh cached articles",
                iconUrls=["xdg:view-refresh"],
                actions=[Action("refresh", "Refresh Wallabag index", lambda: self.updateIndexItems())],
            )
        )

    def _create_filters(self, item: dict):
        return ",".join([item["url"], item["title"].lower(), ",".join(tag["label"] for tag in item["tags"])])

    def _gen_item(self, article):
        return StandardItem(
            text=article["title"] or article["url"],
            subtext=" - ".join([article["url"], ",".join(tag["label"] for tag in article["tags"])]),
            iconUrls=self.iconUrls,
            actions=[
                Action(
                    "open",
                    "Open article in wallabag",
                    lambda u="{}/view/{}".format(self._instance_url, article["id"]): openUrl(u),
                ),
                Action("open-url", "Open article URL", lambda u=article["url"]: openUrl(u)),
                Action("copy", "Copy article URL to clipboard", lambda u=article["url"]: setClipboardText(u)),
            ],
        )

    def _fetch_results(self):
        headers = {"User-Agent": self.user_agent, "Authorization": f"Bearer {self._get_token()}"}
        return (article for article_list in self._get_articles(headers) for article in article_list)

    def _get_articles(self, headers: dict):
        # Set the initial pages so the loop runs at least once
        page, pages = 0, 1
        while page < pages:
            page += 1
            params = {"perPage": self.limit, "page": page}
            url = f"{self._instance_url}/api/entries.json?{parse.urlencode(params)}"
            try:
                response = requests.get(url, headers=headers, timeout=5)
            except requests.ConnectionError:
                warning(f"Unable to establish connection to: {self._instance_url}")
                break
            if response.ok:
                result = response.json()
                pages = int(result["pages"])
                yield result["_embedded"]["items"]
            else:
                warning(f"Got response {response.status_code} querying {url}")
                break

    def _get_token(self):
        if not self._token or not self._token.is_valid():
            self._refresh_token()
        return self._token.access if self._token else None

    def _refresh_token(self):
        url = f"{self._instance_url}/oauth/v2/token"
        debug(f"Fetching token from {url}")
        try:
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
                self._token = Token(response.json())
            else:
                warning(f"Got response: {response.status_code} {response.content}")
        except requests.ConnectionError:
            warning(f"Unable to establish connection to: {self._instance_url}")


class Token:
    def __init__(self, token: dict):
        self.access = token["access_token"]
        self.refresh = token["refresh_token"]
        self._expiry = datetime.now() + timedelta(seconds=(token["expires_in"] / 2))

    def is_valid(self):
        return self._expiry <= datetime.now()
