export function toUnixTime(value) {
    return Math.floor(new Date(value).getTime() / 1000);
}
export function compactTime(value) {
    if (!value)
        return "--";
    return value.replace("T", " ").replace("+00:00", "");
}
export function price(value) {
    if (value === null || value === undefined || Number.isNaN(value))
        return "--";
    return value.toFixed(2);
}
