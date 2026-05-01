'use client';

import { List } from 'react-window';
import { type ReactNode, type CSSProperties } from 'react';

interface VirtualizedListProps<T> {
  items: T[];
  height: number;
  itemHeight: number;
  renderItem: (item: T, index: number, style: CSSProperties) => ReactNode;
  className?: string;
}

interface RowData<T> {
  items: T[];
  renderItem: (item: T, index: number, style: CSSProperties) => ReactNode;
}

function RowRenderer<T>({
  index,
  style,
  data,
}: {
  index: number;
  style: CSSProperties;
  data: RowData<T>;
  [key: string]: unknown;
}) {
  return <>{data.renderItem(data.items[index], index, style)}</>;
}

export default function VirtualizedList<T>({
  items,
  height,
  itemHeight,
  renderItem,
  className,
}: VirtualizedListProps<T>) {
  return (
    <List
      rowCount={items.length}
      rowHeight={itemHeight}
      rowComponent={RowRenderer as never}
      rowProps={{ items, renderItem } as never}
      className={className}
      style={{ height }}
    />
  );
}
