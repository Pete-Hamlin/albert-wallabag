from datetime import datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from time import perf_counter_ns
from urllib import parse

import requests
from albert import *


md_iid = "2.2"
md_version = "3.0"
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
        # Watch for file changes and re-index
        while True:
            self.__callback
            self.__stop_event.wait(self.__cache_length)
            if self.__stop_event.is_set():
                return

    def stop(self):
        self.__stop_event.set()


class Plugin(PluginInstance, IndexQueryHandler):
    iconUrls = [f"file:{Path(__file__).parent}/wallabag.png"]
    limit = 50
    user_agent = "org.albert.wallabag"

    def __init__(self):
        IndexQueryHandler.__init__(self, id=md_id, name=md_name, description=md_description, synopsis="<article-name>", defaultTrigger="wb ")
        PluginInstance.__init__(self, extensions=[self])

        self._instance_url = self.readConfig("instance_url", str) or "http://localhost:80"
        self._username = self.readConfig("username", str) or ""
        self._password = self.readConfig("password", str) or ""
        self._client_id = self.readConfig("client_id", str) or ""
        self._client_secret = self.readConfig("client_secret", str) or ""

        self._cache_length = self.readConfig("cache_length", int) or 15

        self.token = None

        self.thread = ArticleFetcherThread(callback=self.updateIndexItems, cache_length=self.cache_length)
        self.thread.start()

    def finalize(self):
        self.thread.stop()
        self.thread.join()

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
        self._cache_length = value
        self.writeConfig("cache_length", value)

        self.thread.stop()
        self.thread.join()
        self.thread = ArticleFetcherThread(target=self.updateIndexItems, cache_length=self.cache_length)

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
        start = perf_counter_ns()
        data = self.fetch_results()
        index_items = []
        for article in data:
            filter = self.create_filters(article)
            item = self.gen_item(article)
            index_items.append(IndexItem(item=item, string=filter))
        self.setIndexItems(index_items)
        info("Indexed {} articles [{:d} ms]".format(len(index_items), (int(perf_counter_ns() - start) // 1000000)))

    # def handleTriggerQuery(self, query):
    #     stripped = query.string.strip()
    #     if stripped:
    #         GlobalQueryHandler.handleTriggerQuery(query)
    #         query.add(
    #             StandardItem(
    #                 id=md_id,
    #                 text="Refresh cache",
    #                 subtext="Refresh cached articles",
    #                 iconUrls=["xdg:view-refresh"],
    #                 actions=[Action("refresh", "Refresh Wallabag index", lambda: self.updateIndexItems())],
    #             )
    #         )
    #     else:
    #         query.add(
    #             StandardItem(
    #                 id=md_id, text=md_name, subtext="Search for an article saved in Wallabag", iconUrls=self.iconUrls
    #             )
    #         )


    def create_filters(self, item: dict):
        # TODO: Add filter options?
        return ",".join([item["url"], item["title"].lower(), ",".join(tag["label"] for tag in item["tags"])])

    def gen_item(self, article: object):
            return StandardItem(
                id=md_id,
                text=article["title"] or article["url"],
                subtext="{}".format(",".join(tag["label"] for tag in article["tags"])),
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
