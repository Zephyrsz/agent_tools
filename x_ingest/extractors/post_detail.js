async (options = {}) => {
  const config = {
    skipVideos: options.skipVideos !== false,
  };

  const normalize = (value) => (value || "").replace(/\s+\n/g, "\n").trim();
  const statusMatch = location.pathname.match(/\/([^/]+)\/status\/(\d+)/);
  const handleFromUrl = statusMatch ? `@${statusMatch[1]}` : "";
  const statusId = statusMatch ? statusMatch[2] : "";

  function findMainArticle() {
    const articles = [...document.querySelectorAll("article")];
    if (!articles.length) return null;
    return (
      articles.find((article) => {
        const text = normalize(article.innerText);
        return !handleFromUrl || text.toLowerCase().includes(handleFromUrl.toLowerCase());
      }) || articles[0]
    );
  }

  function hasVideo(article) {
    if (!article) return false;
    if (article.querySelector("video")) return true;
    if (article.querySelector('[data-testid="videoPlayer"]')) return true;
    if (article.querySelector('a[href*="/video/"]')) return true;
    return /Play Video|Embedded video|播放视频/i.test(article.innerText || "");
  }

  function extractImages(article) {
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

  function stripDetailChrome(articleText) {
    let lines = articleText.split("\n").map((line) => line.trim()).filter(Boolean);

    while (lines.length && (lines[0] === authorFromArticle(findMainArticle()).displayName || /^@\w+/.test(lines[0]))) {
      lines.shift();
    }

    const footerIndex = lines.findIndex((line) => {
      return (
        /^\d{1,2}:\d{2}\s*[·・]/.test(line) ||
        /^Read \d+ replies/i.test(line) ||
        /^\d+(\.\d+)?[万KkMm]?\s+Views$/i.test(line)
      );
    });
    if (footerIndex >= 0) {
      lines = lines.slice(0, footerIndex);
    }

    return normalize(lines.join("\n\n"));
  }

  function extractText(article) {
    const textNode = article.querySelector('[data-testid="tweetText"]');
    const tweetText = normalize(textNode ? textNode.innerText : "");
    if (tweetText) return tweetText;
    return stripDetailChrome(normalize(article.innerText));
  }

  function authorFromArticle(article) {
    const userName = article?.querySelector('[data-testid="User-Name"]');
    const text = normalize(userName ? userName.innerText : "");
    const handleMatch = text.match(/@\w+/);
    return {
      displayName: text.split("\n")[0] || handleFromUrl.replace(/^@/, ""),
      handle: handleMatch ? handleMatch[0] : handleFromUrl,
    };
  }

  const article = findMainArticle();
  if (!article) {
    return {
      skipped: true,
      skipReason: "No article found",
      url: location.href,
      text: "",
      images: [],
    };
  }

  const video = hasVideo(article);
  if (config.skipVideos && video) {
    return {
      skipped: true,
      skipReason: "Post contains video",
      url: location.href,
      text: "",
      images: [],
      hasVideo: true,
    };
  }

  return {
    skipped: false,
    url: location.href,
    timestamp: article.querySelector("time")?.getAttribute("datetime") || "",
    author: authorFromArticle(article),
    text: extractText(article),
    images: extractImages(article),
    hasVideo: video,
    statusId,
  };
}
