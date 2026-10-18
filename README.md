# Attendance Tracker (Python + Firebase)


## Accounts: each person logs in with their own username and password
Set one environment variable, `USERS`, as `username:password` pairs separated by commas:

    USERS=juan:Pass1word,maria:Another2Pass,teacher.ana:Third3Pass

- On Render: Environment > add `USERS` (it replaces `APP_PASSWORD`), then save; Render redeploys.
- Usernames: letters, numbers, `.`, `_`, `-` only (not case-sensitive). Passwords must not contain `,` or `:`.
- Each login gets its own private students and attendance. People cannot see each other's data.
- To add, remove or change a person, edit `USERS` and save. Removing a person blocks their login but keeps their data in Firebase.
- If `USERS` is not set but `APP_PASSWORD` is, everyone shares one password and one set of data.

## Blocks (Block A to E)
Each login starts with Block A, B, C, D and E. Pick a block from the dropdown at the top;
every block has its own students and attendance.
- **+ Block / Rename / Delete** let you add more blocks (for example Block F), rename or remove one.
- **Import spreadsheet** loads names and attendance into the block you have selected.
- **Download this block** exports the selected block; **Download all blocks** exports every block
  in one Excel file, one sheet per block.
- Data saved before blocks existed is moved into Block A automatically.
