// Image encoders with dpi metadata: TIFF (PackBits, RGB), PNG pHYs, JPEG JFIF density
(function(){
const E = window.PLImg = {};
const CRC = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++){ let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
function crc32(bytes){ let c = 0xFFFFFFFF; for (let i = 0; i < bytes.length; i++) c = CRC[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; }

// PNG: remove any pHYs chunk and insert ours after IHDR
E.pngSetDpi = function(u8, dpi){
  const ppm = Math.round(dpi / 0.0254);
  const chunks = []; let p = 8;
  while (p < u8.length){
    const len = (u8[p] << 24 | u8[p+1] << 16 | u8[p+2] << 8 | u8[p+3]) >>> 0;
    const type = String.fromCharCode(u8[p+4], u8[p+5], u8[p+6], u8[p+7]);
    chunks.push({ type, start: p, end: p + 12 + len });
    p += 12 + len;
  }
  const phys = new Uint8Array(21); const dv = new DataView(phys.buffer);
  dv.setUint32(0, 9); phys.set([0x70,0x48,0x59,0x73], 4); dv.setUint32(8, ppm); dv.setUint32(12, ppm); phys[16] = 1;
  dv.setUint32(17, crc32(phys.subarray(4, 17)));
  const parts = [u8.subarray(0, 8)];
  chunks.forEach(c => { if (c.type === "pHYs") return; parts.push(u8.subarray(c.start, c.end)); if (c.type === "IHDR") parts.push(phys); });
  const total = parts.reduce((a, b) => a + b.length, 0), out = new Uint8Array(total);
  let o = 0; parts.forEach(x => { out.set(x, o); o += x.length; });
  return out;
};

// JPEG: set JFIF density if an APP0 JFIF segment is present
E.jpegSetDpi = function(u8, dpi){
  const out = new Uint8Array(u8);
  if (out[2] === 0xFF && out[3] === 0xE0 && out[6] === 0x4A && out[7] === 0x46 && out[8] === 0x49 && out[9] === 0x46){
    out[13] = 1; out[14] = dpi >> 8; out[15] = dpi & 255; out[16] = dpi >> 8; out[17] = dpi & 255;
  }
  return out;
};

function packBitsRow(src, start, len, out, o){
  let i = 0;
  while (i < len){
    // run of identical bytes?
    let run = 1;
    while (i + run < len && run < 128 && src[start + i + run] === src[start + i]) run++;
    if (run >= 3){ out[o++] = (257 - run) & 0xFF; out[o++] = src[start + i]; i += run; continue; }
    // literal run
    let lit = 0;
    while (i + lit < len && lit < 128){
      if (i + lit + 2 < len && src[start+i+lit] === src[start+i+lit+1] && src[start+i+lit] === src[start+i+lit+2]) break;
      lit++;
    }
    out[o++] = lit - 1;
    for (let k = 0; k < lit; k++) out[o++] = src[start + i + k];
    i += lit;
  }
  return o;
}

// TIFF: baseline RGB, 8 bits per sample, PackBits, one strip, resolution in inches
E.encodeTiff = function(rgba, w, h, dpi){
  const rowBytes = w * 3, rgb = new Uint8Array(rowBytes * h);
  for (let i = 0, j = 0; i < rgba.length; i += 4, j += 3){ rgb[j] = rgba[i]; rgb[j+1] = rgba[i+1]; rgb[j+2] = rgba[i+2]; }
  const packed = new Uint8Array(rgb.length + Math.ceil(rgb.length / 128) + h * 2 + 16);
  let plen = 0;
  for (let y = 0; y < h; y++) plen = packBitsRow(rgb, y * rowBytes, rowBytes, packed, plen);
  const N = 13, ifdOff = 8, ifdSize = 2 + N * 12 + 4;
  const bpsOff = ifdOff + ifdSize, xresOff = bpsOff + 6, yresOff = xresOff + 8, dataOff = yresOff + 8;
  const buf = new ArrayBuffer(dataOff + plen), dv = new DataView(buf), u8 = new Uint8Array(buf);
  u8[0] = 0x49; u8[1] = 0x49; dv.setUint16(2, 42, true); dv.setUint32(4, ifdOff, true);
  dv.setUint16(ifdOff, N, true);
  let p = ifdOff + 2;
  const entry = (tag, type, count, value) => {
    dv.setUint16(p, tag, true); dv.setUint16(p + 2, type, true); dv.setUint32(p + 4, count, true);
    if (type === 3 && count === 1) dv.setUint16(p + 8, value, true); else dv.setUint32(p + 8, value, true);
    p += 12;
  };
  entry(256, 4, 1, w); entry(257, 4, 1, h); entry(258, 3, 3, bpsOff); entry(259, 3, 1, 32773);
  entry(262, 3, 1, 2); entry(273, 4, 1, dataOff); entry(277, 3, 1, 3); entry(278, 4, 1, h);
  entry(279, 4, 1, plen); entry(282, 5, 1, xresOff); entry(283, 5, 1, yresOff); entry(284, 3, 1, 1); entry(296, 3, 1, 2);
  dv.setUint32(p, 0, true);
  dv.setUint16(bpsOff, 8, true); dv.setUint16(bpsOff + 2, 8, true); dv.setUint16(bpsOff + 4, 8, true);
  dv.setUint32(xresOff, dpi, true); dv.setUint32(xresOff + 4, 1, true);
  dv.setUint32(yresOff, dpi, true); dv.setUint32(yresOff + 4, 1, true);
  u8.set(packed.subarray(0, plen), dataOff);
  return u8;
};
})();
