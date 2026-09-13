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
  FlatList,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { fetchComments, fetchMe, fetchReplies, likeComment, postComment, unlikeComment } from '../api/client';
import type { Comment } from '../api/types';
import { colors, radius, space, type, weight } from '../theme';

interface Props {
  outfitId: string;
  visible: boolean;
  onClose: () => void;
  /** Lets the feed card keep its own comment_count in sync without a refetch. */
  onCountChange: (delta: number) => void;
}

function Avatar({ name, size = 32 }: { name: string; size?: number }): React.ReactElement {
  return (
    <View style={[styles.avatar, { width: size, height: size, borderRadius: size / 2 }]}>
      <Text style={[styles.avatarLetter, { fontSize: size * 0.42 }]}>
        {name.charAt(0).toUpperCase()}
      </Text>
    </View>
  );
}

export function CommentSheet({ outfitId, visible, onClose, onCountChange }: Props): React.ReactElement {
  const [items, setItems] = useState<Comment[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [myName, setMyName] = useState('');
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
      .then((me) => setMyName(me.user.display_name || me.user.email.split('@')[0] || '?'))
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
      <Avatar name={comment.author_display_name} size={parentId ? 26 : 32} />
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
      <Pressable style={styles.backdrop} onPress={onClose} accessibilityRole="button" accessibilityLabel="Close comments" />
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={styles.sheetWrap}
      >
        <View style={styles.sheet}>
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
            <Avatar name={myName || '?'} size={30} />
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
              onPress={() => void send()}
              disabled={!draft.trim() || sending}
              accessibilityRole="button"
              accessibilityLabel="Post comment"
            >
              <Text style={[styles.send, (!draft.trim() || sending) && styles.sendDisabled]}>Post</Text>
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.4)' },
  sheetWrap: { justifyContent: 'flex-end' },
  sheet: {
    backgroundColor: colors.background,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    paddingHorizontal: space.lg,
    paddingTop: space.sm,
    paddingBottom: space.lg,
    maxHeight: '75%',
    minHeight: '45%',
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
  list: { flexGrow: 0 },
  empty: { ...type.body, color: colors.textMuted, paddingVertical: space.lg },
  error: { ...type.meta, color: colors.systemError, marginBottom: space.sm },

  avatar: {
    backgroundColor: colors.accent,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarLetter: { color: colors.background, fontWeight: weight.medium },

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
