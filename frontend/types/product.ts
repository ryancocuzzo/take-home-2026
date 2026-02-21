export interface Price {
  price: number;
  currency: string;
  compare_at_price: number | null;
}

export interface Category {
  name: string;
}

export interface Variant {
  name: string;
  attributes: Record<string, string>;
  price: Price | null;
  availability: string | null;
}

export interface Merchant {
  name: string;
  merchant_id: string | null;
}

export interface Offer {
  merchant: Merchant;
  price: Price;
  availability: string | null;
  shipping: string | null;
  promo: string | null;
  source_url: string | null;
}

export interface ProductSummary {
  id: string;
  name: string;
  brand: string;
  price: Price;
  category: Category;
  image_url: string | null;
}

export interface Product {
  name: string;
  price: Price;
  description: string;
  key_features: string[];
  image_urls: string[];
  video_url: string | null;
  category: Category;
  brand: string;
  colors: string[];
  variants: Variant[];
  offers: Offer[];
}
