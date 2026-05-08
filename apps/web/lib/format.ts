export function currencyFormatter(value: number) {
  return new Intl.NumberFormat("en-US", {
    currency: "USD",
    style: "currency",
  }).format(value);
}

export function percentFormatter(value: number) {
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
    style: "percent",
  }).format(value);
}

export function cleanEnum(value: string) {
  return value.includes(".") ? value.split(".").at(-1) ?? value : value;
}
