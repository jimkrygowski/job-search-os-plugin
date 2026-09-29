// d3 and d3-sankey are vendored classic scripts (web/vendor) that define
// the global `d3`; d3-sankey attaches its functions to the same object.
import type * as D3 from "d3";
import type * as D3Sankey from "d3-sankey";

declare global {
  const d3: typeof D3 & typeof D3Sankey;
}

export {};
