async (options = {}) => {
  const config = {
    limit: Number(options.limit || 3),
    maxScrolls: Number(options.maxScrolls || 8),
    waitMs: Number(options.waitMs || 1200),
    skipPinned: options.skipPinned !== false,
    skipVideos: options.skipVideos !== false,
    sortByTimestamp: options.sortByTimestamp !== false,
  };

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const normalize = (value) => (value || "").replace(/\s+\n/g, "\n").trim();

  function statusUrlFromArticle(article) {
    const links = [...article.querySelectorAll('a[href*="/status/"]')];
    const link = links.find((item) => item.querySelector("time")) || links[0];
    if (!link) return "";
    return new URL(link.getAttribute("href"), location.origin).toString();
  }

  function timestampFromArticle(article) {
    const time = article.querySelector("time");
    return time ? time.getAttribute("datetime") || "" : "";
  }

  function authorFromArticle(article) {
    const userName = article.querySelector('[data-testid="User-Name"]');
    const text = normalize(userName ? userName.innerText : "");
    const handleMatch = text.match(/@\w+/);
    return {
      displayName: text.split("\n")[0] || "",
      handle: handleMatch ? handleMatch[0] : "",
    };
  }

  function textFromArticle(article) {
    const textNodes = [...article.querySelectorAll('[data-testid="tweetText"]')];
    if (!textNodes.length) return "";

    // The first tweetText is the timeline item itself. Later tweetText nodes can
    // belong to quoted posts embedded inside the same article.
    return normalize(textNodes[0].innerText);
  }

  function hasVideo(article) {
    if (article.querySelector("video")) return true;
    if (article.querySelector('[data-testid="videoPlayer"]')) return true;
    if (article.querySelector('a[href*="/video/"]')) return true;
    return /Play Video|Embedded video|播放视频/i.test(article.innerText || "");
  }

  function imagesFromArticle(article) {
    const seen = new Set();
    return [...article.querySelectorAll("img")]
      .map((img) => ({
        url: img.currentSrc || img.src || "",
        alt: img.alt || "",
      }))
      .filter((image) => {
        if (!image.url.includes("pbs.twimg.com/media/")) return false;
        if (seen.has(image.url)) return false;
        seen.add(image.url);
        return true;
      });
  }

  function extractVisiblePosts() {
    return [...document.querySelectorAll("article")]
      .map((article) => {
        const articleText = normalize(article.innerText);
        if (config.skipPinned && (/\bPinned\b/i.test(articleText) || articleText.includes("已置顶"))) {
          return null;
        }

        const text = textFromArticle(article);
        if (!text) return null;
        const video = hasVideo(article);
        if (config.skipVideos && video) return null;

        return {
          text,
          url: statusUrlFromArticle(article),
          timestamp: timestampFromArticle(article),
          author: authorFromArticle(article),
          images: imagesFromArticle(article),
          hasVideo: video,
        };
      })
      .filter(Boolean);
  }

  const seen = new Set();
  const posts = [];

  for (let scroll = 0; scroll <= config.maxScrolls; scroll += 1) {
    await sleep(config.waitMs);

    for (const post of extractVisiblePosts()) {
      const key = post.url || post.text;
      if (!key || seen.has(key)) continue;
      seen.add(key);
      posts.push(post);
    }

    window.scrollBy(0, Math.floor(window.innerHeight * 0.85));
  }

  if (config.sortByTimestamp) {
    posts.sort((left, right) => {
      const leftTime = Date.parse(left.timestamp || "") || 0;
      const rightTime = Date.parse(right.timestamp || "") || 0;
      return rightTime - leftTime;
    });
  }

  return {
    sourcePage: location.href,
    capturedAt: new Date().toISOString(),
    count: Math.min(posts.length, config.limit),
    posts: posts.slice(0, config.limit),
  };
}
