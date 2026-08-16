(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.EmbyCleanPagination = api;
})(typeof globalThis === "object" ? globalThis : this, function () {
  function buildPageBuckets(items, pageSize) {
    const size = Math.max(1, Number(pageSize) || 1);
    const pages = [];
    let page = [];
    let index = 0;
    while (index < items.length) {
      const title = items[index].groupTitle;
      let end = index + 1;
      while (end < items.length && items[end].groupTitle === title) end += 1;
      const group = items.slice(index, end);
      if (page.length && page.length + group.length > size) {
        pages.push(page);
        page = [];
      }
      page.push(...group);
      if (page.length >= size) {
        pages.push(page);
        page = [];
      }
      index = end;
    }
    if (page.length) pages.push(page);
    return pages;
  }

  return { buildPageBuckets };
});
