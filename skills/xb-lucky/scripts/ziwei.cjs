#!/usr/bin/env node
'use strict';

/**
 * Local Ziwei chart CLI. No network, persistence, or interpretation-library code.
 * True-solar-time / clock adjustment / China DST logic is a functional
 * reimplementation of MIT-licensed ziwei-doushu modules; see notices.
 */

const ENGINE_VERSION = '2.6.3';
const MINUTES_PER_DAY = 1440;
const SECONDS_PER_DAY = 86400;
const BRANCHES = ['子', '丑', '寅', '卯', '辰', '巳', '午', '未', '申', '酉', '戌', '亥'];
const ATMOSPHERE = {
  木: { color: '青绿', direction: '东' },
  火: { color: '红橙', direction: '南' },
  土: { color: '黄棕', direction: '本地' },
  金: { color: '白金', direction: '西' },
  水: { color: '黑蓝', direction: '北' },
};
const TOPIC_PALACES = {
  project: ['命宫', '官禄', '财帛', '迁移'],
  relationship: ['命宫', '夫妻', '福德', '迁移'],
  general: ['命宫', '官禄', '财帛', '迁移'],
};

// Inclusive ranges, aligned with the reviewed ziwei-doushu XLS_CN convention.
const CHINA_DST = [
  [1935, 5, 1, 9, 30], [1936, 5, 1, 9, 30], [1937, 5, 1, 9, 30],
  [1938, 5, 1, 9, 30], [1939, 5, 1, 9, 30], [1940, 5, 1, 9, 30],
  [1941, 5, 1, 9, 30], [1942, 5, 1, 9, 30], [1943, 5, 1, 9, 30],
  [1944, 5, 1, 9, 30], [1945, 5, 1, 9, 30], [1946, 5, 1, 9, 30],
  [1947, 5, 1, 9, 30], [1948, 5, 1, 9, 30], [1949, 5, 1, 9, 30],
  [1950, 5, 1, 9, 30], [1951, 5, 1, 9, 30], [1952, 3, 1, 10, 31],
  [1953, 4, 1, 10, 31], [1954, 4, 1, 10, 31], [1955, 5, 1, 9, 30],
  [1956, 5, 1, 9, 30], [1957, 4, 1, 9, 30], [1958, 4, 1, 9, 30],
  [1959, 4, 1, 9, 30], [1960, 6, 1, 9, 30], [1961, 6, 1, 9, 30],
  [1974, 4, 1, 10, 31], [1975, 4, 1, 10, 31], [1979, 7, 1, 9, 30],
  [1986, 5, 4, 9, 14], [1987, 4, 12, 9, 13], [1988, 4, 10, 9, 11],
  [1989, 4, 16, 9, 17], [1990, 4, 15, 9, 16], [1991, 4, 14, 9, 15],
];

class LuckyError extends Error {
  constructor(code, message, details = undefined) {
    super(message);
    this.code = code;
    this.details = details;
  }
}

function fail(code, message, details) {
  throw new LuckyError(code, message, details);
}

function mod(value, base) {
  return ((value % base) + base) % base;
}

function pad(value) {
  return String(value).padStart(2, '0');
}

function isoDate(parts) {
  return `${String(parts.year).padStart(4, '0')}-${pad(parts.month)}-${pad(parts.day)}`;
}

function dateParts(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || '');
  if (!match) fail('E_DATE', '日期必须为 YYYY-MM-DD，且必须是真实公历日期');
  const parts = { year: Number(match[1]), month: Number(match[2]), day: Number(match[3]) };
  const date = new Date(Date.UTC(parts.year, parts.month - 1, parts.day));
  if (date.getUTCFullYear() !== parts.year || date.getUTCMonth() !== parts.month - 1 || date.getUTCDate() !== parts.day) {
    fail('E_DATE', `不存在的公历日期：${value}`);
  }
  return parts;
}

function shiftDate(parts, offset) {
  const shifted = new Date(Date.UTC(parts.year, parts.month - 1, parts.day + offset));
  return { year: shifted.getUTCFullYear(), month: shifted.getUTCMonth() + 1, day: shifted.getUTCDate() };
}

function addDays(value, count) {
  return isoDate(shiftDate(dateParts(value), count));
}

function daysBetween(start, end) {
  const a = dateParts(start);
  const b = dateParts(end);
  return Math.round((Date.UTC(b.year, b.month - 1, b.day) - Date.UTC(a.year, a.month - 1, a.day)) / SECONDS_PER_DAY / 1000);
}

function parseClock(value) {
  const match = /^(\d{2}):(\d{2})$/.exec(value || '');
  if (!match) fail('E_TIME', '时间必须为 HH:MM（24 小时制）');
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  if (hour > 23 || minute > 59) fail('E_TIME', `无效时间：${value}`);
  return { hour, minute };
}

function isChinaDST(parts) {
  for (const [year, startMonth, startDay, endMonth, endDay] of CHINA_DST) {
    if (parts.year !== year) continue;
    if (parts.month > startMonth && parts.month < endMonth) return true;
    if (parts.month === startMonth) {
      if (parts.day >= startDay) return true;
    } else if (parts.month === endMonth && parts.day <= endDay) return true;
  }
  return false;
}

function isLeapYear(year) {
  return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
}

function dayOfYear(parts) {
  return Math.floor((Date.UTC(parts.year, parts.month - 1, parts.day) - Date.UTC(parts.year, 0, 0)) / 86400000);
}

function equationOfTimeMinutes(parts, hour, minute) {
  const daysInYear = isLeapYear(parts.year) ? 366 : 365;
  const fractionalHour = hour + minute / 60;
  const gamma = (2 * Math.PI / daysInYear) * (dayOfYear(parts) - 1 + (fractionalHour - 12) / 24);
  return 229.18 * (
    0.000075 + 0.001868 * Math.cos(gamma) - 0.032077 * Math.sin(gamma)
    - 0.014615 * Math.cos(2 * gamma) - 0.040849 * Math.sin(2 * gamma)
  );
}

function branchFromSolarMinutes(normalizedMinutes) {
  if (normalizedMinutes >= 1380 || normalizedMinutes < 60) return 0;
  return Math.floor((normalizedMinutes - 60) / 120) + 1;
}

function calculateTrueSolarTime(parts, hour, minute, longitude, utcOffsetMinutes) {
  const corrected = longitude !== undefined;
  const meridian = utcOffsetMinutes / 4;
  const longitudeCorrectionMinutes = corrected ? (longitude - meridian) * 4 : 0;
  const eot = corrected ? equationOfTimeMinutes(parts, hour, minute) : 0;
  const totalCorrectionMinutes = longitudeCorrectionMinutes + eot;
  const rawMinutes = hour * 60 + minute + totalCorrectionMinutes;
  const roundedTotalSeconds = Math.round(rawMinutes * 60);
  const dayOffset = Math.floor(roundedTotalSeconds / SECONDS_PER_DAY);
  const secondOfDay = mod(roundedTotalSeconds, SECONDS_PER_DAY);
  return {
    corrected,
    longitudeCorrectionMinutes,
    equationOfTimeMinutes: eot,
    totalCorrectionMinutes,
    dayOffset,
    hour: Math.floor(secondOfDay / 3600),
    minute: Math.floor((secondOfDay % 3600) / 60),
    second: secondOfDay % 60,
    normalizedMinutes: secondOfDay / 60,
    branch: branchFromSolarMinutes(secondOfDay / 60),
  };
}

function resolveZiweiDayOffset(solar, lateZishiRule) {
  const isLateZishi = solar.branch === 0 && solar.normalizedMinutes >= 1380;
  return solar.dayOffset + (isLateZishi && lateZishiRule === 'next-day' ? 1 : 0);
}

function parseNumber(value, label, integer = false) {
  const number = Number(value);
  if (!Number.isFinite(number) || (integer && !Number.isInteger(number))) fail('E_ARGUMENT', `${label} 不是有效${integer ? '整数' : '数值'}：${value}`);
  return number;
}

function prepareChartInput(options) {
  const originalDate = dateParts(options.date);
  let adjustedDate = { ...originalDate };
  const clock = parseClock(options.time);
  const timeBasis = options['time-basis'] || 'standard';
  if (!['standard', 'clock'].includes(timeBasis)) fail('E_ARGUMENT', '--time-basis 只接受 standard 或 clock');
  if (!['male', 'female'].includes(options.gender)) fail('E_GENDER', '--gender 必须明确为 male 或 female；这是引擎参数');
  const lateZishi = options['late-zishi'] || 'next-day';
  if (!['next-day', 'current-day'].includes(lateZishi)) fail('E_ARGUMENT', '--late-zishi 只接受 next-day 或 current-day');

  let standardMinusClockMinutes = 0;
  const customDelta = options['standard-minus-clock-minutes'];
  if (customDelta !== undefined) standardMinusClockMinutes = parseNumber(customDelta, '--standard-minus-clock-minutes', true);
  const region = options.region || 'unknown';
  if (!['china-mainland', 'other', 'unknown'].includes(region)) fail('E_ARGUMENT', '--region must be china-mainland or other');
  if (timeBasis === 'clock' && region === 'unknown') fail('E_REGION_REQUIRED', 'Clock input requires --region china-mainland|other');
  if (options['dst-confirmed'] && region !== 'china-mainland') fail('E_ARGUMENT', '--dst-confirmed requires --region china-mainland');
  if (timeBasis === 'clock' && region === 'other' && customDelta === undefined) fail('E_CLOCK_OFFSET_REQUIRED', 'Other regions require an explicit --standard-minus-clock-minutes, including 0');
  const dstDate = region === 'china-mainland' && isChinaDST(originalDate);
  if (timeBasis === 'clock' && dstDate) {
    if (customDelta !== undefined || options['dst-confirmed']) {
      if (customDelta !== undefined && options['dst-confirmed']) fail('E_ARGUMENT', '夏令时确认与自定义时差只能选一种');
      if (options['dst-confirmed']) standardMinusClockMinutes = -60;
    } else {
      fail('E_DST_CONFIRMATION_REQUIRED', '该日期处于中国大陆历史夏令时表；若输入是当年钟表读数，请确认后加 --dst-confirmed（减 60 分钟），否则用 --time-basis standard');
    }
  }
  if (timeBasis === 'standard' && (customDelta !== undefined || options['dst-confirmed'])) {
    fail('E_ARGUMENT', '标准时间输入不能再附加夏令时或自定义钟表平移');
  }

  let clockAdjustedMinutes = clock.hour * 60 + clock.minute + standardMinusClockMinutes;
  if (clockAdjustedMinutes < 0 || clockAdjustedMinutes >= MINUTES_PER_DAY) {
    fail('E_CLOCK_CROSS_DAY', '钟表时间平移后跨日；请由用户核对日期与时间，脚本不自动改日期');
  }
  const adjustedHour = Math.floor(clockAdjustedMinutes / 60);
  const adjustedMinute = clockAdjustedMinutes % 60;

  let longitude;
  if (options.longitude !== undefined) {
    longitude = parseNumber(options.longitude, '--longitude');
    if (longitude < -180 || longitude > 180) fail('E_ARGUMENT', '经度必须位于 -180 到 180');
    if (options['utc-offset'] === undefined) fail('E_TIMEZONE_REQUIRED', '提供经度校正时必须同时明确 --utc-offset（分钟，东正西负）');
  }
  const utcOffsetMinutes = options['utc-offset'] === undefined ? 480 : parseNumber(options['utc-offset'], '--utc-offset', true);
  if (utcOffsetMinutes < -840 || utcOffsetMinutes > 840) fail('E_ARGUMENT', 'UTC 偏移必须位于 -840 到 840 分钟');

  const solar = calculateTrueSolarTime(adjustedDate, adjustedHour, adjustedMinute, longitude, utcOffsetMinutes);
  const resolvedOffset = resolveZiweiDayOffset(solar, lateZishi);
  const chartDate = shiftDate(adjustedDate, resolvedOffset);
  const rawTimeIndex = branchFromSolarMinutes(clockAdjustedMinutes);
  const sameDatasetBasis = isoDate(chartDate) === isoDate(adjustedDate) && solar.branch === rawTimeIndex && standardMinusClockMinutes === 0;

  return {
    original: { date: isoDate(originalDate), time: `${pad(clock.hour)}:${pad(clock.minute)}`, timeBasis, region },
    clockAdjustment: {
      chinaDSTDate: dstDate,
      standardMinusClockMinutes,
      adjustedDate: isoDate(adjustedDate),
      adjustedTime: `${pad(adjustedHour)}:${pad(adjustedMinute)}`,
    },
    trueSolar: {
      applied: solar.corrected,
      longitude: longitude === undefined ? null : longitude,
      utcOffsetMinutes,
      longitudeCorrectionMinutes: solar.longitudeCorrectionMinutes,
      equationOfTimeMinutes: solar.equationOfTimeMinutes,
      totalCorrectionMinutes: solar.totalCorrectionMinutes,
      correctedDateBeforeLateZishi: isoDate(shiftDate(adjustedDate, solar.dayOffset)),
      correctedTime: `${pad(solar.hour)}:${pad(solar.minute)}:${pad(solar.second)}`,
      dayOffset: solar.dayOffset,
    },
    lateZishiRule: lateZishi,
    chartDate: isoDate(chartDate),
    chartTimeIndex: solar.branch,
    chartTimeBranch: BRANCHES[solar.branch],
    gender: options.gender,
    datasetLookup: {
      key: `${isoDate(adjustedDate)}-${rawTimeIndex}-${options.gender}`,
      date: isoDate(adjustedDate),
      timeIndex: rawTimeIndex,
      gender: options.gender,
      sameChartBasis: sameDatasetBasis,
    },
  };
}

function loadEngine() {
  let astro;
  let version;
  try {
    version = require('iztro/package.json').version;
    astro = require('iztro').astro;
  } catch (error) {
    fail('E_IZTRO_MISSING', `找不到 iztro ${ENGINE_VERSION}；请在用户授权后安装到外部运行目录并设置 NODE_PATH`, { cause: error.message });
  }
  if (version !== ENGINE_VERSION) fail('E_ENGINE_VERSION', `排盘依赖版本不符：需要 ${ENGINE_VERSION}，实际 ${version}`);
  if (!astro || typeof astro.bySolar !== 'function') fail('E_ENGINE_API', 'iztro 2.6.3 未提供预期 astro.bySolar 接口');
  return { astro, version };
}

function starsOf(palace) {
  return [...palace.majorStars, ...palace.minorStars].map((star) => ({
    name: star.name,
    brightness: star.brightness || null,
    mutagen: star.mutagen || null,
  }));
}

function summarizeChart(chart) {
  const palaces = chart.palaces.map((palace) => ({
    name: palace.name,
    heavenlyStem: palace.heavenlyStem,
    earthlyBranch: palace.earthlyBranch,
    isBodyPalace: palace.isBodyPalace,
    majorStars: palace.majorStars.map((star) => ({ name: star.name, brightness: star.brightness || null, mutagen: star.mutagen || null })),
    minorStars: palace.minorStars.map((star) => ({ name: star.name, brightness: star.brightness || null, mutagen: star.mutagen || null })),
    decadal: palace.decadal,
  }));
  const mutagens = { 禄: [], 权: [], 科: [], 忌: [] };
  for (const palace of palaces) {
    for (const star of [...palace.majorStars, ...palace.minorStars]) {
      if (star.mutagen && mutagens[star.mutagen]) mutagens[star.mutagen].push({ star: star.name, palace: palace.name });
    }
  }
  const ming = palaces.find((palace) => palace.name === '命宫');
  const fiveElement = (chart.fiveElementsClass || '')[0];
  return {
    solarDate: chart.solarDate,
    lunarDate: chart.lunarDate,
    chineseDate: chart.chineseDate,
    time: chart.time,
    timeRange: chart.timeRange,
    gender: chart.gender,
    fiveElementsClass: chart.fiveElementsClass,
    soul: chart.soul,
    body: chart.body,
    earthlyBranchOfBodyPalace: chart.earthlyBranchOfBodyPalace,
    earthlyBranchOfSoulPalace: chart.earthlyBranchOfSoulPalace,
    lifePalaceFirstMajorStar: ming && ming.majorStars.length ? ming.majorStars[0].name : null,
    palaces,
    mutagens,
    atmosphere: ATMOSPHERE[fiveElement] ? { ...ATMOSPHERE[fiveElement], layer: '氛围层，不作现实决策依据' } : null,
  };
}

function summarizePeriod(period) {
  if (!period) return null;
  return {
    index: period.index,
    name: period.name,
    heavenlyStem: period.heavenlyStem,
    earthlyBranch: period.earthlyBranch,
    palaceNames: period.palaceNames,
    mutagen: period.mutagen,
    nominalAge: period.nominalAge,
    stars: period.stars,
  };
}

function summarizeHoroscope(chart, targetDate) {
  const date = isoDate(dateParts(targetDate));
  const horoscope = chart.horoscope(date);
  return {
    targetDate: horoscope.solarDate,
    lunarDate: horoscope.lunarDate,
    decadal: summarizePeriod(horoscope.decadal),
    age: summarizePeriod(horoscope.age),
    yearly: summarizePeriod(horoscope.yearly),
    monthly: summarizePeriod(horoscope.monthly),
    daily: summarizePeriod(horoscope.daily),
    hourly: summarizePeriod(horoscope.hourly),
  };
}

function makeChart(options) {
  const input = prepareChartInput(options);
  const { astro, version } = loadEngine();
  astro.config({ yearDivide: 'normal' });
  let chart;
  try {
    chart = astro.bySolar(input.chartDate, input.chartTimeIndex, input.gender === 'male' ? '男' : '女', true, 'zh-CN');
  } catch (error) {
    fail('E_CHART', '排盘引擎拒绝本次输入', { cause: error.message, chartDate: input.chartDate, chartTimeIndex: input.chartTimeIndex });
  }
  const warnings = [];
  if (!input.trueSolar.applied) warnings.push('未提供经度，本次未做真太阳时校正');
  if (input.clockAdjustment.chinaDSTDate && input.original.timeBasis === 'standard') warnings.push('日期命中历史夏令时表，但按用户声明的标准时间输入，未减 60 分钟');
  if (!input.datasetLookup.sameChartBasis) warnings.push('数据集若使用，只能作原始时钟参考，不能视为同一校正盘');
  return {
    schemaVersion: 1,
    command: 'chart',
    nature: '传统命理文化演绎，不是科学预测或现实建议',
    engine: { name: 'iztro', version, yearDivide: 'normal', brightness: 'iztro-native' },
    input,
    chart: summarizeChart(chart),
    horoscope: options['target-date'] ? summarizeHoroscope(chart, options['target-date']) : null,
    warnings,
  };
}

function pickDay(options) {
  const start = options.start;
  const end = options.end;
  dateParts(start);
  dateParts(end);
  const span = daysBetween(start, end);
  if (span < 0 || span > 30) fail('E_RANGE', '择日范围必须为同一正向区间，且最多 31 天');
  const topic = options.topic || 'project';
  if (!TOPIC_PALACES[topic]) fail('E_ARGUMENT', '--topic 只接受 project、relationship 或 general');
  const selectedPalaces = TOPIC_PALACES[topic];
  const candidates = [];
  for (let index = 0; index <= span; index += 1) {
    const date = addDays(start, index);
    const result = makeChart({ ...options, date });
    const support = [];
    const attention = [];
    for (const palace of result.chart.palaces.filter((item) => selectedPalaces.includes(item.name))) {
      for (const star of [...palace.majorStars, ...palace.minorStars]) {
        if (['禄', '权', '科'].includes(star.mutagen)) support.push(`${star.name}化${star.mutagen}@${palace.name}`);
        if (star.mutagen === '忌') attention.push(`${star.name}化忌@${palace.name}`);
      }
    }
    candidates.push({
      date,
      chartTime: `${result.input.chartTimeBranch}时（序号 ${result.input.chartTimeIndex}）`,
      supportCount: support.length,
      attentionCount: attention.length,
      support,
      attention,
      datasetLookup: result.input.datasetLookup,
      warnings: result.warnings,
    });
  }
  candidates.sort((a, b) => b.supportCount - a.supportCount || a.attentionCount - b.attentionCount || a.date.localeCompare(b.date));
  const first = candidates[0];
  const preferred = candidates.filter((item) => item.supportCount === first.supportCount && item.attentionCount === first.attentionCount).map((item) => item.date);
  return {
    schemaVersion: 1,
    command: 'pick-day',
    nature: '公开象征规则的排序，不是成功率、预测或现实发布建议',
    topic,
    selectedPalaces,
    rule: '关键宫每见禄/权/科计 1 个支持标记，每见忌计 1 个注意标记；支持多者优先，再比较注意少者，同分并列',
    preferred,
    candidates,
    realityGate: '人员、预算、权限、准备、天气与平台窗口等现实硬约束优先于本排序',
  };
}

function selfTest() {
  const assert = require('node:assert/strict');
  assert.equal(branchFromSolarMinutes(0), 0);
  assert.equal(branchFromSolarMinutes(60), 1);
  assert.equal(branchFromSolarMinutes(1380), 0);
  assert.equal(isChinaDST({ year: 1990, month: 5, day: 1 }), true);
  assert.equal(isChinaDST({ year: 1990, month: 10, day: 1 }), false);
  assert.throws(() => dateParts('2026-02-30'), /不存在的公历日期/);
  assert.throws(() => prepareChartInput({ date: '1990-05-01', time: '08:00', gender: 'male', 'time-basis': 'clock', region: 'china-mainland' }), (error) => error.code === 'E_DST_CONFIRMATION_REQUIRED');
  const sample = prepareChartInput({ date: '2026-11-04', time: '10:00', gender: 'male', longitude: '121.47', 'utc-offset': '480' });
  assert.equal(sample.chartTimeIndex, 5);
  const result = makeChart({ date: '2026-11-04', time: '10:00', gender: 'male' });
  assert.equal(result.chart.lifePalaceFirstMajorStar, '巨门');
  assert.equal(result.command, 'chart');
  return { passed: true, checks: 9, engine: ENGINE_VERSION, sampleLifePalaceFirstMajorStar: result.chart.lifePalaceFirstMajorStar };
}

function parseArgs(argv) {
  const options = {};
  const flags = new Set(['dst-confirmed']);
  const allowed = new Set(['date','time','gender','target-date','time-basis','region','standard-minus-clock-minutes','longitude','utc-offset','late-zishi','start','end','topic',...flags]);
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith('--')) fail('E_ARGUMENT', `无法识别参数：${token}`);
    const key = token.slice(2);
    if (!allowed.has(key)) fail('E_ARGUMENT', `Unknown option: ${token}`);
    if (flags.has(key)) options[key] = true;
    else {
      index += 1;
      if (index >= argv.length) fail('E_ARGUMENT', `参数 ${token} 缺值`);
      options[key] = argv[index];
    }
  }
  return options;
}

function help() {
  console.log(`xb-lucky local CLI (iztro ${ENGINE_VERSION})

chart --date YYYY-MM-DD --time HH:MM --gender male|female [--target-date YYYY-MM-DD]
      [--time-basis standard|clock] [--region china-mainland|other] [--dst-confirmed]
      [--standard-minus-clock-minutes N] [--longitude DEG --utc-offset MIN]
      [--late-zishi next-day|current-day]
pick-day --start YYYY-MM-DD --end YYYY-MM-DD --time HH:MM --gender male|female
         [--topic project|relationship|general] [same correction options]
self-test

Network is never used. Output is JSON on stdout; errors are JSON on stderr.`);
}

function main() {
  const [command, ...rest] = process.argv.slice(2);
  if (!command || command === '--help' || command === '-h') return help();
  const options = parseArgs(rest);
  let output;
  if (command === 'chart') output = makeChart(options);
  else if (command === 'pick-day') output = pickDay(options);
  else if (command === 'self-test') output = selfTest();
  else fail('E_ARGUMENT', `未知命令：${command}`);
  process.stdout.write(`${JSON.stringify(output, null, 2)}\n`);
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    const payload = error instanceof LuckyError
      ? { error: error.code, message: error.message, details: error.details || null }
      : { error: 'E_INTERNAL', message: error.message };
    process.stderr.write(`${JSON.stringify(payload, null, 2)}\n`);
    process.exitCode = 2;
  }
}

module.exports = {
  branchFromSolarMinutes,
  calculateTrueSolarTime,
  isChinaDST,
  prepareChartInput,
  makeChart,
  selfTest,
};
