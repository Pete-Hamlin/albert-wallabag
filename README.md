# Albert Obsidian

A python plugin to allow [albert](https://github.com/albertlauncher/albert) to interact with a [wallabag](https://wallabag.org/) instance.
Currently supports the following features
- Trigger query search of articles (default `wb`) by URL/title/tags
- Global query results from vault notes via URL/title/tags
- Queries support:
    - Opening of articles in wallabag
    - Opening of original article URLs in browser
    - Copying link URLs
    - Archiving link
    - Deleting link
- An indexer that re-indexes on a configurable interval (default: `15` minutes)
- Some [basic settings](#settings) to customise behaviour

## Install

You will need to [setup an API client](https://doc.wallabag.org/en/developer/api/oauth) for your wallabag instance.

Run the follow from a terminal:

```shell
git clone https://github.com/Pete-Hamlin/albert-wallabag.git $HOME/.local/share/albert/python/plugins/wallabag
```

Then enable the plugin from the albert settings panel (you **must** enable the python plugin for this plugin to be visible/loadable)

## Settings

- `instance_url`: URL where your linkding instance is hosted - default `http://localhost:80`
- `username`: Wallabag username. - default `None`
- `password`: Wallabag password. - default `None`
- `client_id`: Wallabag client_id for API client. - default `None`
- `client_secret`: Wallabag client_secret for API client. - default `None`
- `api_key`: A valid API token for the linkding API. The application automatically generates an API token for each user, which can be accessed through the Settings page. - default `None`
- `cache_length`: The length of time to wait between refreshing the index of articles (in minutes). - default `15`
