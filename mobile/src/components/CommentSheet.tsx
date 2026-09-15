/**
 * Comment thread — SPEC+ (docs/spec-deviations.md #32). A bottom sheet, not a
 * new full-screen route, so tapping the comment icon on a feed card's rail
 * never navigates away from the feed. Modeled on TikTok's comment sheet:
 * a count in the header, an explicit close button, an avatar per commenter,
 * per-comment likes, and one level of replies (a reply to a reply is not
 * supported — matches how TikTok actually renders threads, flattened).
 * There is no delete here on purpose — removed, not just hidden.
 */
import { Ionicons } from '@expo/vector-icons';
import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Dimensions,
  FlatList,
  Keyboard,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { fetchComments, fetchMe, fetchReplies, likeComment, postComment, unlikeComment } from '../api/client';
import type { Comment } from '../api/types';
import { Avatar } from './primitives';
import { colors, radius, space, type, weight } from '../theme';

// Numeric, not percentage — a percentage height only resolves reliably
// against a parent with its own definite (non-content-based) height, which
// this sheet's parent chain (an absolutely-positioned, bottom-pinned View)
// doesn't have. Computing pixels directly from the window is what actually
// guarantees the sheet renders at a predictable height instead of
// collapsing to content size with the backdrop showing through above it.
const WINDOW_HEIGHT = Dimensions.get('window').height;
const SHEET_MAX_HEIGHT = WINDOW_HEIGHT * 0.75;
const SHEET_MIN_HEIGHT = 200;
// Real breathing room above the keyboard, not zero — some keyboards (seen
// on-device: Samsung Keyboard's own suggestion/tool row above the actual
// keys) render extra chrome that isn't fully reflected in the height
// `keyboardDidShow` reports, so pinning the composer at exactly that
// reported height still left it flush against the keyboard's visible top
// edge. A fixed margin is simpler and more robust than trying to measure
// that discrepancy precisely per-keyboard/device. First tried 24px —
// still close enough that a tap on "Post" could land on the keyboard's
// own suggestion strip instead of the button (confirmed on-device: taps
// were landing on the keyboard, not Post). 56px gives real touch-target
// clearance, not just visual clearance.
const KEYBOARD_GAP = 56;

/** Tracks the keyboard's own height directly rather than leaning on
 * `KeyboardAvoidingView`'s heuristics — those fought against `sheet`'s
 * own `maxHeight`/`minHeight` (a fixed 45% of the window) and pushed the
 * composer below the visible area instead of shrinking the comment list
 * to make room for it. Slides the whole sheet up by the keyboard's exact
 * height and shrinks its own max height to match, so the composer always
 * stays pinned just above the keyboard. */
function useKeyboardHeight(): number {
  const [height, setHeight] = useState(0);
  useEffect(() => {
    const show = Keyboard.addListener('keyboardDidShow', (event) =>
      setHeight(event.endCoordinates.height),
    );
    const hide = Keyboard.addListener('keyboardDidHide', () => setHeight(0));
    return () => {
      show.remove();
      hide.remove();
    };
  }, []);
  return height;
}

interface Props {
  outfitId: string;
  visible: boolean;
  onClose: () => void;
  /** Lets the feed card keep its own comment_count in sync without a refetch. */
  onCountChange: (delta: number) => void;
}

export function CommentSheet({ outfitId, visible, onClose, onCountChange }: Props): React.ReactElement {
  const keyboardHeight = useKeyboardHeight();
  // SPEC+ (docs/spec-deviations.md #39, round 5) — the real cause of "Post
  // silently dismisses the keyboard instead of posting": confirmed via a
  // real device reproduction with diagnostic logging (not reasoned from a
  // screenshot, unlike every earlier round here) that NEITHER the Post
  // button's onPressIn NOR the full-screen backdrop's onPress fired at
  // all when the bug happened — the tap never reached React Native's touch
  // system in the first place. That rules out a JS-side timing race
  // entirely and points at Android's own gesture-navigation edge zone
  // swallowing the touch before delivery to any app view, which happens
  // when tappable content renders inside that OS-reserved strip. Every
  // other bottom-pinned element in this app (TabBar.tsx) already accounts
  // for `insets.bottom`; this sheet never did.
  const insets = useSafeAreaInsets();
  const [items, setItems] = useState<Comment[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [myName, setMyName] = useState('');
  const [myAvatarUrl, setMyAvatarUrl] = useState<string | null>(null);
  const [replyTarget, setReplyTarget] = useState<Comment | null>(null);
  const [replies, setReplies] = useState<Record<string, Comment[]>>({});
  const [repliesLoading, setRepliesLoading] = useState<Record<string, boolean>>({});

  const load = useCallback(async (): Promise<void> => {
    setLoading(true);
    try {
      const page = await fetchComments(outfitId);
      setItems(page.items);
      setTotalCount(page.total_count);
      setError(null);
    } catch {
      setError('Could not load comments.');
    } finally {
      setLoading(false);
    }
  }, [outfitId]);

  useEffect(() => {
    if (!visible) return;
    void load();
    fetchMe()
      .then((me) => {
        setMyName(me.user.display_name || me.user.email.split('@')[0] || '?');
        setMyAvatarUrl(me.user.avatar_url ?? null);
      })
      .catch(() => undefined);
  }, [visible, load]);

  const toggleReplies = async (comment: Comment): Promise<void> => {
    if (replies[comment.comment_id]) {
      setReplies((existing) => {
        const next = { ...existing };
        delete next[comment.comment_id];
        return next;
      });
      return;
    }
    setRepliesLoading((existing) => ({ ...existing, [comment.comment_id]: true }));
    try {
      const page = await fetchReplies(outfitId, comment.comment_id);
      setReplies((existing) => ({ ...existing, [comment.comment_id]: page.items }));
    } catch {
      // Leave collapsed — the "View replies" row stays tappable to retry.
    } finally {
      setRepliesLoading((existing) => ({ ...existing, [comment.comment_id]: false }));
    }
  };

  const toggleCommentLike = (comment: Comment, parentId: string | null): void => {
    const updateIn = (list: Comment[]): Comment[] =>
      list.map((item) =>
        item.comment_id === comment.comment_id
          ? {
              ...item,
              liked_by_me: !item.liked_by_me,
              like_count: item.like_count + (item.liked_by_me ? -1 : 1),
            }
          : item,
      );

    if (parentId) {
      setReplies((existing) => ({ ...existing, [parentId]: updateIn(existing[parentId] ?? []) }));
    } else {
      setItems((existing) => updateIn(existing));
    }

    const call = comment.liked_by_me ? unlikeComment : likeComment;
    call(outfitId, comment.comment_id).catch(() => {
      // Roll back on failure.
      if (parentId) {
        setReplies((existing) => ({ ...existing, [parentId]: updateIn(existing[parentId] ?? []) }));
      } else {
        setItems((existing) => updateIn(existing));
      }
    });
  };

  const send = async (): Promise<void> => {
    const body = draft.trim();
    if (!body || sending) return;
    setSending(true);
    try {
      const comment = await postComment(outfitId, body, replyTarget?.comment_id);
      if (replyTarget) {
        setReplies((existing) => ({
          ...existing,
          [replyTarget.comment_id]: [...(existing[replyTarget.comment_id] ?? []), comment],
        }));
        setItems((existing) =>
          existing.map((item) =>
            item.comment_id === replyTarget.comment_id
              ? { ...item, reply_count: item.reply_count + 1 }
              : item,
          ),
        );
      } else {
        setItems((existing) => [...existing, comment]);
      }
      setTotalCount((count) => count + 1);
      onCountChange(1);
      setDraft('');
      setReplyTarget(null);
    } catch {
      setError('Could not post that comment. Try again.');
    } finally {
      setSending(false);
    }
  };

  const renderComment = (comment: Comment, parentId: string | null): React.ReactElement => (
    <View style={parentId ? styles.replyRow : styles.row}>
      <Avatar
        name={comment.author_display_name}
        uri={comment.author_avatar_url}
        size={parentId ? 26 : 32}
      />
      <View style={styles.rowBody}>
        <Text style={styles.author}>{comment.author_display_name}</Text>
        <Text style={styles.body}>{comment.body}</Text>
        <View style={styles.rowActions}>
          {!parentId ? (
            <Pressable
              onPress={() => setReplyTarget(comment)}
              accessibilityRole="button"
              accessibilityLabel={`Reply to ${comment.author_display_name}`}
            >
              <Text style={styles.replyLink}>Reply</Text>
            </Pressable>
          ) : null}
          {!parentId && comment.reply_count > 0 ? (
            <Pressable
              onPress={() => void toggleReplies(comment)}
              accessibilityRole="button"
              accessibilityLabel={`View ${comment.reply_count} replies`}
            >
              <Text style={styles.replyLink}>
                {replies[comment.comment_id]
                  ? 'Hide replies'
                  : `View ${comment.reply_count} ${comment.reply_count === 1 ? 'reply' : 'replies'}`}
              </Text>
            </Pressable>
          ) : null}
          {repliesLoading[comment.comment_id] ? (
            <ActivityIndicator size="small" color={colors.textMuted} />
          ) : null}
        </View>
      </View>
      <Pressable
        onPress={() => toggleCommentLike(comment, parentId)}
        style={styles.likeButton}
        accessibilityRole="button"
        accessibilityLabel={comment.liked_by_me ? 'Unlike comment' : 'Like comment'}
      >
        <Text style={[styles.likeGlyph, comment.liked_by_me && styles.likeGlyphActive]}>
          {comment.liked_by_me ? '♥' : '♡'}
        </Text>
        <Text style={styles.likeCount}>{comment.like_count}</Text>
      </Pressable>
    </View>
  );

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.overlay}>
        <Pressable
          style={styles.backdrop}
          onPress={onClose}
          accessibilityRole="button"
          accessibilityLabel="Close comments"
        />
        <View
          style={[
            styles.sheetWrap,
            { bottom: keyboardHeight > 0 ? keyboardHeight + KEYBOARD_GAP : 0 },
          ]}
        >
        <View
          style={[
            styles.sheet,
            {
              maxHeight: Math.min(
                SHEET_MAX_HEIGHT,
                WINDOW_HEIGHT - keyboardHeight - KEYBOARD_GAP - space.xl,
              ),
              // The fix (see the insets comment above): reserve the
              // system gesture strip inside the sheet's own bottom
              // padding, always — not just when the keyboard is closed —
              // so the composer/Post button never renders inside it.
              paddingBottom: space.lg + insets.bottom,
            },
          ]}
        >
          <View style={styles.handle} />
          <View style={styles.titleRow}>
            <Text style={styles.title}>{totalCount} {totalCount === 1 ? 'comment' : 'comments'}</Text>
            <Pressable onPress={onClose} accessibilityRole="button" accessibilityLabel="Close comments" hitSlop={8}>
              <Ionicons name="close" size={22} color={colors.text} />
            </Pressable>
          </View>

          {error ? <Text style={styles.error}>{error}</Text> : null}

          {loading ? (
            <ActivityIndicator color={colors.textMuted} style={styles.spinner} />
          ) : (
            <FlatList
              data={items}
              keyExtractor={(item) => item.comment_id}
              style={styles.list}
              keyboardShouldPersistTaps="handled"
              ListEmptyComponent={
                <Text style={styles.empty}>No comments yet — be the first to say something.</Text>
              }
              renderItem={({ item }) => (
                <View>
                  {renderComment(item, null)}
                  {(replies[item.comment_id] ?? []).map((reply) => (
                    <View key={reply.comment_id}>{renderComment(reply, item.comment_id)}</View>
                  ))}
                </View>
              )}
            />
          )}

          {replyTarget ? (
            <View style={styles.replyingToRow}>
              <Text style={styles.replyingToText}>
                Replying to {replyTarget.author_display_name}
              </Text>
              <Pressable onPress={() => setReplyTarget(null)} accessibilityRole="button" accessibilityLabel="Cancel reply">
                <Ionicons name="close" size={16} color={colors.textMuted} />
              </Pressable>
            </View>
          ) : null}

          <View style={styles.composerRow}>
            <Avatar name={myName || '?'} uri={myAvatarUrl} size={30} />
            <TextInput
              style={styles.input}
              placeholder={replyTarget ? `Reply to ${replyTarget.author_display_name}` : 'Add a comment'}
              placeholderTextColor={colors.textMuted}
              value={draft}
              onChangeText={setDraft}
              maxLength={500}
              multiline
            />
            <Pressable
              // onPressIn, not onPress: tapping this button blurs the
              // TextInput, which dismisses the keyboard as a side effect —
              // and the moment that starts, the sheet's own position
              // (pinned relative to keyboard height) shifts down. onPress
              // only fires on release, by which point this button has
              // already moved out from under the finger, so the tap
              // silently misses. onPressIn fires on touch-down, before any
              // of that reflow can happen.
              onPressIn={() => void send()}
              disabled={!draft.trim() || sending}
              accessibilityRole="button"
              accessibilityLabel="Post comment"
            >
              <Text style={[styles.send, (!draft.trim() || sending) && styles.sendDisabled]}>Post</Text>
            </Pressable>
          </View>
        </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  // A plain column layout here (the pre-fix shape) relied on `backdrop`
  // (flex:1) and `sheetWrap` stacking correctly by luck — absolute
  // positioning both against this one full-screen wrapper is what
  // actually guarantees the sheet stays pinned to the bottom with no gap
  // showing the screen behind it through.
  overlay: { flex: 1 },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(0,0,0,0.4)' },
  sheetWrap: { position: 'absolute', left: 0, right: 0, bottom: 0 },
  sheet: {
    backgroundColor: colors.background,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    paddingHorizontal: space.lg,
    paddingTop: space.sm,
    paddingBottom: space.lg,
    maxHeight: SHEET_MAX_HEIGHT,
    minHeight: SHEET_MIN_HEIGHT,
  },
  handle: {
    alignSelf: 'center',
    width: 36,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.border,
    marginBottom: space.sm,
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: space.sm,
  },
  title: { ...type.bodyMedium, color: colors.text },
  spinner: { marginTop: space.xl },
  // flexShrink (not flexGrow: 0) — this is the one element that should
  // give up space first when the sheet's own maxHeight shrinks to make
  // room for the keyboard, so the composer below it never gets pushed
  // out of view.
  list: { flexShrink: 1 },
  empty: { ...type.body, color: colors.textMuted, paddingVertical: space.lg },
  error: { ...type.meta, color: colors.systemError, marginBottom: space.sm },

  row: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: space.sm,
    paddingVertical: space.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  replyRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: space.sm,
    paddingVertical: space.sm,
    paddingLeft: space.xl,
  },
  rowBody: { flex: 1 },
  author: { ...type.meta, color: colors.text, fontWeight: weight.medium },
  body: { ...type.body, color: colors.text, marginTop: 2 },
  rowActions: { flexDirection: 'row', alignItems: 'center', gap: space.md, marginTop: space.xs },
  replyLink: { ...type.meta, color: colors.textMuted, fontWeight: weight.medium },

  // §2.6: amber is the accent, never red.
  likeButton: { alignItems: 'center', paddingHorizontal: space.xs },
  likeGlyph: { fontSize: 16, color: colors.textMuted },
  likeGlyphActive: { color: colors.accent },
  likeCount: { ...type.meta, color: colors.textMuted, marginTop: 2 },

  replyingToRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: colors.surface,
    borderRadius: radius.sm,
    paddingHorizontal: space.sm,
    paddingVertical: space.xs,
    marginTop: space.sm,
  },
  replyingToText: { ...type.meta, color: colors.textMuted },

  composerRow: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    marginTop: space.sm,
    gap: space.sm,
  },
  input: {
    flex: 1,
    ...type.body,
    color: colors.text,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: space.md,
    paddingVertical: space.sm,
    maxHeight: 100,
  },
  send: { ...type.bodyMedium, color: colors.accent, fontWeight: weight.medium, paddingVertical: space.sm },
  sendDisabled: { color: colors.textMuted },
});
