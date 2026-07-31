"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Star, ExternalLink, ShoppingCart, ShoppingBag, Check, AlertCircle, GitCompare, MessageSquare, LogIn } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { productImageUrl } from "@/lib/images";
import { useCart } from "@/lib/cart-context";
import { useAuth } from "@/lib/auth-context";

interface ProductData {
  id?: string;
  name?: string;
  price?: number;
  original_price?: number;
  image_url?: string;
  rating?: number;
  review_count?: number;
  category?: string;
  brand?: string;
  description?: string;
  on_sale?: boolean;
}

const CATEGORY_COLORS: Record<string, string> = {
  electronics: "bg-sky-100 text-sky-800 border-sky-200",
  clothing: "bg-violet-100 text-violet-800 border-violet-200",
  home: "bg-emerald-100 text-emerald-800 border-emerald-200",
  sports: "bg-orange-100 text-orange-800 border-orange-200",
  books: "bg-amber-100 text-amber-800 border-amber-200",
};

interface ChatProductCardProps {
  data: ProductData;
  onAction?: (message: string) => void;
}

/**
 * Product/order ids are Postgres UUIDs. The LLM composing a card block is
 * instructed to copy the real id from the tool result, but it occasionally
 * fabricates a name-derived slug ("sony-wh1000xm5-001") instead. Those ids
 * 404 against /api/cart/items and /products/[id], which surfaced as an
 * "Add to Cart" button that only ever flipped to "Retry". Treat anything
 * that isn't a UUID as no id at all: the card still renders (with Compare /
 * Reviews, which work off the name), it just doesn't offer actions that are
 * guaranteed to fail.
 */
const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function ChatProductCard({ data, onAction }: ChatProductCardProps) {
  const { cart, addItem } = useCart();
  const { isAuthenticated } = useAuth();
  const router = useRouter();
  const [optimisticAdded, setOptimisticAdded] = useState(false);
  const [error, setError] = useState(false);

  if (!data.name) return null;

  const productId = data.id && UUID_RE.test(data.id) ? data.id : undefined;

  // "Added" derives from cart state so it persists across re-renders and
  // reflects reality (e.g. after navigating back to the conversation).
  const inCart =
    !!productId && !!cart?.items?.some((i) => i.product_id === productId);
  const showAdded = inCart || optimisticAdded;

  const hasDiscount =
    data.original_price && data.original_price > (data.price || 0);
  const discountPct = hasDiscount
    ? Math.round((1 - (data.price || 0) / data.original_price!) * 100)
    : 0;
  const catColor =
    CATEGORY_COLORS[(data.category || "").toLowerCase()] ||
    "bg-muted text-muted-foreground border-border";

  return (
    <div className="rounded-xl border border-border bg-card shadow-sm max-w-md overflow-hidden transition-shadow hover:shadow-md">
      {/* Top: image + info */}
      <div className="flex gap-3 p-3 pb-2">
        {/* Image */}
        <div className="size-20 shrink-0 rounded-lg overflow-hidden bg-muted flex items-center justify-center">
          {productId ? (
            <img
              src={productImageUrl(productId, 100, 100, data.image_url, data.category)}
              alt={data.name}
              className="size-full object-cover"
              loading="lazy"
            />
          ) : (
            <ShoppingBag className="size-7 text-muted-foreground" />
          )}
        </div>

        {/* Info */}
        <div className="flex flex-1 flex-col gap-0.5 min-w-0">
          <h4 className="text-sm font-semibold text-foreground line-clamp-2 leading-tight">
            {data.name}
          </h4>

          <div className="flex items-center gap-1.5 flex-wrap">
            {data.brand && (
              <span className="text-[11px] text-muted-foreground">{data.brand}</span>
            )}
            {data.category && (
              <Badge
                variant="outline"
                className={`text-[10px] px-1.5 py-0 ${catColor}`}
              >
                {data.category}
              </Badge>
            )}
          </div>

          {data.description && (
            <p className="text-[11px] text-muted-foreground line-clamp-2 leading-snug">
              {data.description}
            </p>
          )}

          {/* Price */}
          <div className="flex items-center gap-1.5 mt-auto pt-0.5">
            {data.price != null && (
              <span className="text-base font-bold text-primary">
                ${data.price.toFixed(2)}
              </span>
            )}
            {hasDiscount && (
              <span className="text-xs text-muted-foreground line-through">
                ${data.original_price!.toFixed(2)}
              </span>
            )}
            {hasDiscount && discountPct > 0 && (
              <Badge className="bg-red-500 text-white border-0 text-[9px] px-1.5 py-0">
                {discountPct}% OFF
              </Badge>
            )}
          </div>

          {/* Rating */}
          {data.rating != null && (
            <div className="flex items-center gap-1">
              <div className="flex items-center">
                {Array.from({ length: 5 }, (_, i) => (
                  <Star
                    key={i}
                    className={`size-3 ${
                      i < Math.round(data.rating!)
                        ? "fill-amber-400 text-amber-400"
                        : "fill-muted text-muted"
                    }`}
                  />
                ))}
              </div>
              <span className="text-[11px] text-muted-foreground">
                {data.rating.toFixed(1)}
                {data.review_count != null && ` (${data.review_count})`}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Action buttons */}
      {(productId || onAction) && (
        <div className="flex items-center gap-2 border-t border-border px-3 py-2">
          {productId && !isAuthenticated && (
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              onClick={(e) => {
                e.stopPropagation();
                router.push("/login");
              }}
            >
              <LogIn className="mr-1 size-3" />
              Sign in to buy
            </Button>
          )}
          {productId && isAuthenticated && (
            <Button
              size="sm"
              className={`h-7 text-xs ${
                error
                  ? "bg-red-600 hover:bg-red-700 text-white"
                  : showAdded
                    ? "bg-emerald-600 hover:bg-emerald-700 text-white"
                    : "bg-primary hover:opacity-90 text-primary-foreground"
              }`}
              disabled={showAdded && !error}
              onClick={(e) => {
                e.stopPropagation();
                if (!productId) return;
                // Optimistic — flip UI immediately, fire the network call
                // in the background so the chat stays responsive.
                setError(false);
                setOptimisticAdded(true);
                addItem(productId)
                  .then(() => {
                    // Mirror the typed-message flow: ask the chat to show
                    // the updated cart so a checkout card renders.
                    if (onAction && data.name) {
                      onAction(`I just added ${data.name} to my cart. Show me my updated cart.`);
                    }
                  })
                  .catch(() => {
                    setOptimisticAdded(false);
                    setError(true);
                    setTimeout(() => setError(false), 2500);
                  });
              }}
            >
              {error ? (
                <AlertCircle className="mr-1 size-3" />
              ) : showAdded ? (
                <Check className="mr-1 size-3" />
              ) : (
                <ShoppingCart className="mr-1 size-3" />
              )}
              {error ? "Retry" : showAdded ? "Added" : "Add to Cart"}
            </Button>
          )}
          {productId && (
            <Link
              href={isAuthenticated ? `/products/${productId}` : `/shop/products/${productId}`}
              target="_blank"
              rel="noopener noreferrer"
            >
              <Button size="sm" variant="outline" className="h-7 text-xs">
                <ExternalLink className="mr-1 size-3" />
                Details
              </Button>
            </Link>
          )}
          {onAction && data.name && (
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              onClick={(e) => {
                e.stopPropagation();
                onAction(`Compare the ${data.name} with similar products`);
              }}
            >
              <GitCompare className="mr-1 size-3" />
              Compare
            </Button>
          )}
          {onAction && data.name && (
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              onClick={(e) => {
                e.stopPropagation();
                onAction(`What are the reviews like for the ${data.name}?`);
              }}
            >
              <MessageSquare className="mr-1 size-3" />
              Reviews
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
