function repetitionReason(text) {
  const tail = String(text).slice(-4096);
  if (/([^\s])\1{95,}/.test(tail)) return '同一字符连续重复';
  const compact = tail.replace(/\[(?:回复已中断|检测到重复输出[^\]]*)\]\s*$/, '').replace(/\s+/g, '');
  for (let size = 24; size <= Math.min(512, Math.floor(compact.length/4)); size++) {
    const block = compact.slice(-size);
    if (compact.endsWith(block.repeat(4))) return '同一段落循环重复';
  }
  return null;
}
module.exports = { repetitionReason };
