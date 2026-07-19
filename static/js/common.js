/* StadiumIQ shared frontend helpers.
   Loaded before the page scripts (app.js / ops.js) so both share one
   implementation of DOM lookup and API fetching - no duplication, no deps. */
"use strict";

/**
 * Shorthand for document.getElementById.
 * @param {string} id - element id
 * @returns {HTMLElement} the matching element
 */
function $(id) {
  return document.getElementById(id);
}

/**
 * fetch() wrapper that resolves to parsed JSON and throws a readable Error
 * (using the API's `detail` message when present) on any non-2xx response.
 * @param {string} url - same-origin API url
 * @param {RequestInit} [options] - fetch options
 * @returns {Promise<any>} parsed JSON body
 */
async function fetchJSON(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch (_) {
      /* body was not JSON - keep the status text */
    }
    throw new Error(detail);
  }
  return res.json();
}
