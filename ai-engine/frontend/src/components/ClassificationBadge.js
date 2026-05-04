import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { classificationColors } from '../lib/format';
export function ClassificationBadge({ classification, score, size = 'md' }) {
    const { bg, text, border } = classificationColors(classification);
    const sizeClasses = size === 'sm' ? 'text-[10px] px-1.5 py-0.5' : 'text-xs px-2 py-0.5';
    return (_jsxs("span", { className: `inline-flex items-center gap-1.5 rounded-full border font-mono font-medium uppercase tracking-wide ${bg} ${text} ${border} ${sizeClasses}`, children: [classification, score !== undefined && (_jsx("span", { className: "text-gray-300/80", children: score.toFixed(2) }))] }));
}
